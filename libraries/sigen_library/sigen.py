import aiohttp
import logging
import time
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
import base64
import re

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

logger = logging.getLogger(__name__)

REGION_BASE_URLS = {
    'eu': "https://api-eu.sigencloud.com/",
    'cn': "https://api-cn.sigencloud.com/",
    'apac': "https://api-apac.sigencloud.com/",
    'au': "https://api-aus.sigencloud.com/",
    'us': "https://api-us.sigencloud.com/"
}

is_dev_test = True
batch_key = '8c7fa517c8442b1a' if is_dev_test else 'xo6as8fjnq3kljfo'


async def create_dynamic_methods(sigen):
    # Create dynamic methods for operational modes
    await sigen.get_operational_modes()
    operational_modes = sigen.operational_modes
    
    # Create methods for default modes
    for mode in operational_modes['defaultWorkingModes']:
        method_name = f"set_operational_mode_{mode['label'].lower().replace(' ', '_').replace('-', '_')}"
        mode_value = int(mode['value'])
        
        # Need to create a closure to capture the current value of mode_value
        def create_default_method(mode_value):
            async def default_method(self):
                await self.set_operational_mode(mode_value, -1)
            return default_method
        
        method = create_default_method(mode_value)
        method.__name__ = method_name
        setattr(Sigen, method_name, method)
    
    # Create methods for custom modes
    for mode in operational_modes['energyProfileItems']:
        method_name = f"set_operational_mode_{mode['name'].lower().replace(' ', '_').replace('-', '_')}"
        profile_id = mode['profileId']
        
        # Need to create a closure to capture the current value of profile_id
        def create_custom_method(profile_id):
            async def custom_method(self):
                await self.set_operational_mode(9, profile_id)
            return custom_method
        
        method = create_custom_method(profile_id)
        method.__name__ = method_name
        setattr(Sigen, method_name, method)
    
    # Create dynamic methods for smart loads
    await sigen.get_smart_loads()
    smart_loads = sigen.smart_loads
    
    if smart_loads:
        for load in smart_loads:
            # Create normalized name for the method
            safe_name = load['name'].lower().replace(' ', '_').replace('-', '_')
            load_path = load['path']
            
            # Create enable method
            enable_method_name = f"enable_smart_load_{safe_name}"
            
            def create_enable_method(path):
                async def enable_method(self):
                    """Enable a specific smart load"""
                    return await self.set_smart_load_state(path, 1)  # 1 = ON
                return enable_method
                
            enable_method = create_enable_method(load_path)
            enable_method.__name__ = enable_method_name
            setattr(Sigen, enable_method_name, enable_method)
            
            # Create disable method
            disable_method_name = f"disable_smart_load_{safe_name}"
            
            def create_disable_method(path):
                async def disable_method(self):
                    """Disable a specific smart load"""
                    return await self.set_smart_load_state(path, 0)  # 0 = OFF
                return disable_method
                
            disable_method = create_disable_method(load_path)
            disable_method.__name__ = disable_method_name
            setattr(Sigen, disable_method_name, disable_method)


class Sigen:

    def __init__(self, username: str, password: str, region: str = 'eu', api_url: str=None):
        self.ac_ev_dlm_status = None
        self.ac_ev_max_current = None
        self.ac_ev_last_set_current = None
        self.username = username
        self.password = encrypt_password(password)
        self.token_info = None
        self.access_token = None
        self.refresh_token = None
        self.token_expiry = None
        # Initialising variables that will be populated later
        self.station_id = None
        self._smart_load_id_map = {}  # Maps load paths to smart load IDs
        self.smart_loads = []
        self.headers = None
        self.operational_modes = None

        if region not in REGION_BASE_URLS:
            if api_url is None:
                raise ValueError(f"Unsupported region '{region}'. Supported regions are: {', '.join(REGION_BASE_URLS.keys())}")
            else:
                self.BASE_URL = api_url
        else:
            self.BASE_URL = REGION_BASE_URLS[region]

    async def async_initialize(self):
        """Initializes the Sigen client by fetching the token, station info, and smart load IDs."""
        await self.get_access_token()
        await self.fetch_station_info()
        await self.fetch_smart_load_ids()
        await create_dynamic_methods(self)

    async def fetch_smart_load_ids(self):
        """Fetch and cache the mapping between load paths and their smartLoadIds."""
        await self.ensure_valid_token()
        
        # First get all smart loads to know their paths
        url = f"{self.BASE_URL}device/system/device/systemDevice/card"
        params = {
            'stationId': self.station_id,
            'showNewGenerator': 'true'
        }
        
        async with aiohttp.ClientSession() as session:
            # Get the list of smart loads
            async with session.get(url, headers=self.headers, params=params) as response:
                if response.status != 200:
                    logger.error(f"Failed to get smart loads list: Status {response.status}")
                    return
                    
                response_json = await response.json()
                if response_json.get('code') != 0 or 'data' not in response_json:
                    logger.error(f"Invalid response format when getting smart loads list: {response_json}")
                    return
                    
                smart_loads = response_json['data']
                
                # For each load, fetch its smartLoadId
                for load in smart_loads:
                    if 'path' not in load:
                        continue
                        
                    load_path = load['path']
                    load_name = load.get('name', f"Load {load_path}")
                    
                    # Get the smartLoadId
                    load_details_url = f"{self.BASE_URL}device/tp-device/smart-loads"
                    load_details_params = {
                        'stationId': self.station_id,
                        'loadPath': load_path
                    }
                    
                    try:
                        async with session.get(load_details_url, headers=self.headers, 
                                          params=load_details_params) as load_details_response:
                            if load_details_response.status != 200:
                                logger.warning(f"Failed to get smart load details for {load_name}: Status {load_details_response.status}")
                                continue
                                
                            load_details = await load_details_response.json()
                            if load_details.get('code') != 0 or 'data' not in load_details:
                                logger.warning(f"Invalid response format while getting load details for {load_name}: {load_details}")
                                continue
                                
                            smart_load_id = load_details['data'].get('smartLoadId')
                            if smart_load_id is None:
                                logger.warning(f"No smartLoadId found for load {load_name} (path: {load_path})")
                                continue
                                
                            # Cache the ID
                            self._smart_load_id_map[load_path] = smart_load_id
                            logger.debug(f"Cached smartLoadId {smart_load_id} for load {load_name} (path: {load_path})")
                    except Exception as e:
                        logger.error(f"Error fetching smartLoadId for load {load_name}: {e}")
                        
                logger.info(f"Cached {len(self._smart_load_id_map)} smart load IDs")

    async def get_smart_loads(self):
        """
        Get all smart loads for the station with their consumption statistics.
        
        Returns a list of smart loads with details like:
        - name: Name of the smart load
        - path: Path identifier needed for controlling the smart load
        - valueWithUnit: Power consumption with unit
        - manualSwitch: Current state (1=on, 0=off)
        - todayConsumption: Energy consumed today (e.g., "4.79 kWh")
        - monthConsumption: Energy consumed this month (e.g., "93.04 kWh")
        - lifetimeConsumption: Total energy consumed (e.g., "93.04 kWh")
        
        :return: List of smart loads with consumption data
        """
        await self.ensure_valid_token()
        
        # Fetch the basic smart loads information
        url = f"{self.BASE_URL}device/system/device/systemDevice/card"
        params = {
            'stationId': self.station_id,
            'showNewGenerator': 'true'
        }
        
        async with aiohttp.ClientSession() as session:
            # Get the list of smart loads
            async with session.get(url, headers=self.headers, params=params) as response:
                if response.status != 200:
                    logger.error(f"Failed to get smart loads: Status {response.status}")
                    return self.smart_loads or []
                    
                response_json = await response.json()
                if response_json.get('code') != 0 or 'data' not in response_json:
                    logger.error(f"Invalid response format when getting smart loads: {response_json}")
                    return self.smart_loads or []
                
                smart_loads = response_json['data']
                
                # For each smart load, fetch consumption statistics using cached smartLoadIds
                for load in smart_loads:
                    # Set default values for consumption statistics
                    load['todayConsumption'] = '0.00 kWh'
                    load['monthConsumption'] = '0.00 kWh'
                    load['lifetimeConsumption'] = '0.00 kWh'
                    
                    if 'path' not in load:
                        continue
                        
                    load_path = load['path']
                    load_name = load.get('name', f"Load {load_path}")
                    
                    # Check if we have a cached smartLoadId for this path
                    if load_path not in self._smart_load_id_map:
                        # If not in cache, try to fetch it now
                        try:
                            # We're missing this ID, try to refresh our cache
                            if len(self._smart_load_id_map) == 0:  # If cache is empty, do a full refresh
                                logger.debug(f"Smart load ID cache is empty, refreshing all IDs")
                                await self.fetch_smart_load_ids()
                            else:  # Otherwise just fetch this specific ID
                                logger.debug(f"Fetching missing smartLoadId for {load_name} (path: {load_path})")
                                load_details_url = f"{self.BASE_URL}device/tp-device/smart-loads"
                                load_details_params = {
                                    'stationId': self.station_id,
                                    'loadPath': load_path
                                }
                                
                                async with session.get(load_details_url, headers=self.headers, 
                                                    params=load_details_params) as load_details_response:
                                    if load_details_response.status == 200:
                                        load_details = await load_details_response.json()
                                        if load_details.get('code') == 0 and 'data' in load_details:
                                            smart_load_id = load_details['data'].get('smartLoadId')
                                            if smart_load_id is not None:
                                                self._smart_load_id_map[load_path] = smart_load_id
                                                logger.debug(f"Added missing smartLoadId {smart_load_id} for {load_name}")
                        except Exception as e:
                            logger.error(f"Error fetching missing smartLoadId for {load_name}: {e}")
                    
                    # Check again if we now have the ID
                    if load_path in self._smart_load_id_map:
                        smart_load_id = self._smart_load_id_map[load_path]
                        load['smartLoadId'] = smart_load_id
                        
                        # Fetch consumption data
                        try:
                            consumption_url = f"{self.BASE_URL}data-process/sigen/station/statistics/real-time-consumption"
                            consumption_params = {
                                'stationId': self.station_id,
                                'loadPath': load_path,
                                'smartLoadId': smart_load_id
                            }
                            
                            async with session.get(consumption_url, headers=self.headers, 
                                                params=consumption_params) as consumption_response:
                                if consumption_response.status == 200:
                                    consumption_data = await consumption_response.json()
                                    if consumption_data.get('code') == 0 and 'data' in consumption_data:
                                        # Add consumption statistics to the load data
                                        if consumption_data['data'].get('todayConsumption'):
                                            load['todayConsumption'] = consumption_data['data'].get('todayConsumption')
                                        if consumption_data['data'].get('monthConsumption'):
                                            load['monthConsumption'] = consumption_data['data'].get('monthConsumption')
                                        if consumption_data['data'].get('lifetimeConsumption'):
                                            load['lifetimeConsumption'] = consumption_data['data'].get('lifetimeConsumption')
                                        logger.debug(f"Added consumption data for {load_name}: "
                                                    f"today={load['todayConsumption']}, "
                                                    f"month={load['monthConsumption']}, "
                                                    f"lifetime={load['lifetimeConsumption']}")
                        except Exception as e:
                            logger.error(f"Error fetching consumption data for {load_name}: {e}")
                
                # Update the cached smart loads
                self.smart_loads = smart_loads
                return smart_loads

    async def get_access_token(self):
        url = f"{self.BASE_URL}auth/oauth/token"
        data = {
            'username': self.username,
            'password': self.password,
            'grant_type': 'password'
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=data, auth=aiohttp.BasicAuth('sigen', 'sigen')) as response:
                if response.status == 401:
                    raise Exception(
                        f"\n\nPOST {url}\n\nFailed to get access token for user '{self.username}'\nResponse code: {response.status} \nResponse text: '{await response.text()}'\nCheck basic auth is working.")
                if response.status == 200:
                    response_json = await response.json()
                    if 'data' not in response_json:
                        raise Exception(
                            f"\n\nPOST {url}\n\nFailed to get access token for user '{self.username}'\nResponse text: '{await response.text()}'")
                    response_data = response_json['data']
                    if response_data is None or 'access_token' not in response_data or 'refresh_token' not in response_data or 'expires_in' not in response_data:
                        raise Exception(
                            f"\n\nPOST {url}\n\nFailed to get access token for user '{self.username}'\nResponse text: '{await response.text()}'")
                    self.token_info = response_data
                    self.access_token = self.token_info['access_token']
                    self.refresh_token = self.token_info['refresh_token']
                    self.token_expiry = time.time() + self.token_info['expires_in']
                    self.headers = {
                        'Authorization': f'Bearer {self.access_token}',
                        'Content-Type': 'application/json'
                    }
                else:
                    raise Exception(
                        f"\n\nPOST {url}\n\nFailed to get access token for user '{self.username}'\nResponse code: {response.status} \nResponse text: '{await response.text()}'")

    async def refresh_access_token(self):
        url = f"{self.BASE_URL}auth/oauth/token"
        data = {
            'grant_type': 'refresh_token',
            'refresh_token': self.refresh_token
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=data, auth=aiohttp.BasicAuth('sigen', 'sigen')) as response:
                if response.status == 200:
                    response_json = await response.json()
                    response_data = response_json['data']
                    if response_data and 'access_token' in response_data and 'refresh_token' in response_data and 'expires_in' in response_data:
                        self.access_token = response_data['access_token']
                        self.refresh_token = response_data['refresh_token']
                        self.token_expiry = time.time() + response_data['expires_in']
                        self.headers['Authorization'] = f'Bearer {self.access_token}'
                    else:
                        raise Exception(
                            f"\n\nPOST {url}\n\nFailed to refresh access token\nResponse text: '{await response.text()}'")
                else:
                    raise Exception(
                        f"\n\nPOST {url}\n\nFailed to refresh access token\nResponse code: {response.status} \nResponse text: '{await response.text()}'")

    async def ensure_valid_token(self):
        if time.time() >= self.token_expiry:
            await self.refresh_access_token()

    async def fetch_station_info(self):
        await self.ensure_valid_token()
        url = f"{self.BASE_URL}device/owner/station/home"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=self.headers) as response:
                data = (await response.json())['data']
                self.station_id = data['stationId']

                if data['hasAcCharger']:
                    # safely get first element of list data['acSnList']
                    self.ac_sn = data['acSnList'][0] if data['acSnList'] else None

                self.dc_sn = data['dcSnList'][0] if data['dcSnList'] else None

                logger.debug(f"Station ID: {self.station_id}")
                logger.debug(f"Has PV: {data['hasPv']}")
                logger.debug(f"Has EV: {data['hasEv']}")
                logger.debug(f"hasAcCharger: {data['hasAcCharger']}")
                logger.debug(f"acSnList: {data['acSnList']}")
                logger.debug(f"dcSnList: {data['dcSnList']}")
                logger.debug(f"On Grid: {data['onGrid']}")
                logger.debug(f"PV Capacity: {data['pvCapacity']} kW")
                logger.debug(f"Battery Capacity: {data['batteryCapacity']} kWh")

                return data

    async def get_energy_flow(self):
        await self.ensure_valid_token()
        url = f"{self.BASE_URL}device/sigen/station/energyflow?id={self.station_id}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=self.headers) as response:
                return (await response.json())['data']

    async def get_operational_mode(self):
        await self.ensure_valid_token()
        url = f"{self.BASE_URL}device/energy-profile/mode/current/{self.station_id}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=self.headers) as response:
                response_data = (await response.json())['data']
                current_mode = response_data['currentMode']
                current_profile_id = response_data['currentProfileId']

                if self.operational_modes is None:
                    await self.get_operational_modes()

                # Check if it's a default mode or custom mode
                if current_mode != 9:
                    # It's a default mode
                    for mode in self.operational_modes['defaultWorkingModes']:
                        if mode['value'] == str(current_mode):
                            return mode['label']
                else:
                    # It's a custom mode
                    for mode in self.operational_modes['energyProfileItems']:
                        if mode['profileId'] == current_profile_id:
                            return mode['name']

                return "Unknown mode"

    async def fetch_operational_modes(self):
        await self.ensure_valid_token()
        url = f"{self.BASE_URL}device/energy-profile/mode/all/{self.station_id}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=self.headers) as response:
                self.operational_modes = (await response.json())['data']

    async def set_operational_mode(self, mode: int, profile_id: int = -1):
        await self.ensure_valid_token()
        url = f"{self.BASE_URL}device/energy-profile/mode"
        payload = {
            'stationId': self.station_id,
            'operationMode': mode,
            'profileId': profile_id
        }
        async with aiohttp.ClientSession() as session:
            async with session.put(url, headers=self.headers, json=payload) as response:
                return await response.json()

    async def get_operational_modes(self):
        if not self.operational_modes:
            await self.fetch_operational_modes()
        return self.operational_modes

    async def set_ac_ev_current(self, amps: int):
        await self.ensure_valid_token()
        url = f"{self.BASE_URL}device/acevse/charge/current"
        params = {
            'stationId': self.station_id,
            'current': amps
        }
        async with aiohttp.ClientSession() as session:
            async with session.put(url, headers=self.headers, params=params) as response:
                return await response.json()

    async def get_ac_ev_current(self):
        """
        Get Current Info for AC EVSE. E.g.

        :return:
{
    "code": 0,
    "msg": "success",
    "data": {
        "lastSetCurrent": 30.0,
        "maxCurrent": 30.0,
        "dlmStatus": 1
    }
}
        """
        await self.ensure_valid_token()
        url = f"{self.BASE_URL}device/acevse/charge/read/current"
        params = {
            'stationId': self.station_id,
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=self.headers, params=params) as response:
                json_response = await response.json()
                self.ac_ev_last_set_current = json_response['data']['lastSetCurrent']
                self.ac_ev_max_current = json_response['data']['maxCurrent']
                self.ac_ev_dlm_status = json_response['data']['dlmStatus']
                return json_response

    async def set_ac_ev_dlm_status(self, new_status: int):
        """
        Set DLM Status for AC EVSE.
        :param new_status: 0 (off) or 1 (on)
        :return:
        """
        # check if 1 or 0 entered for new_status
        if new_status not in [0, 1]:
            raise ValueError("DLM new_status must be 0 or 1")

        await self.ensure_valid_token()
        url = f"{self.BASE_URL}device/acevse/more-setting"
        payload = {
            'chargingOutputCurrent': None,
            'outputMode': None,
            'stationId': self.station_id,
            'dlmStatus': new_status,
            'meterPhase': None,
            'homeCircuitBreaker': None,
            'phaseAutoSwitch': None,
            'offGridCharge': None,
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=self.headers, json=payload) as response:
                return await response.json()
                
    async def get_smart_loads(self):
        """
        Get all smart loads for the station with their consumption statistics.
        
        Returns a list of smart loads with details like:
        - name: Name of the smart load
        - path: Path identifier needed for controlling the smart load
        - valueWithUnit: Power consumption with unit
        - manualSwitch: Current state (1=on, 0=off)
        - todayConsumption: Energy consumed today (e.g., "4.79 kWh")
        - monthConsumption: Energy consumed this month (e.g., "93.04 kWh")
        - lifetimeConsumption: Total energy consumed (e.g., "93.04 kWh")
        
        :return: List of smart loads with consumption data
        """
        await self.ensure_valid_token()
        # First, get the basic smart loads information
        url = f"{self.BASE_URL}device/system/device/systemDevice/card"
        params = {
            'stationId': self.station_id,
            'showNewGenerator': 'true'
        }
        
        async with aiohttp.ClientSession() as session:
            # Get the list of smart loads
            async with session.get(url, headers=self.headers, params=params) as response:
                response_json = await response.json()
                smart_loads = response_json['data']
                
                # For each smart load, fetch its consumption statistics and enhance the data
                for load in smart_loads:
                    # Set default values for consumption statistics to ensure they always exist
                    load['todayConsumption'] = '0.00 kWh'
                    load['monthConsumption'] = '0.00 kWh'
                    load['lifetimeConsumption'] = '0.00 kWh'
                    
                    if 'path' in load:
                        try:
                            # First, get the smartLoadId for this load
                            load_details_url = f"{self.BASE_URL}device/tp-device/smart-loads"
                            load_details_params = {
                                'stationId': self.station_id,
                                'loadPath': load['path']
                            }
                            
                            async with session.get(load_details_url, headers=self.headers, 
                                               params=load_details_params) as load_details_response:
                                if load_details_response.status == 200:
                                    load_details = await load_details_response.json()
                                    if load_details.get('code') == 0 and 'data' in load_details:
                                        smart_load_id = load_details['data'].get('smartLoadId')
                                        if smart_load_id is not None:
                                            load['smartLoadId'] = smart_load_id
                                            logger.debug(f"Retrieved smartLoadId {smart_load_id} for load {load.get('name')} (path: {load['path']})")
                                            
                                            # Now fetch consumption statistics for this load
                                            consumption_url = f"{self.BASE_URL}data-process/sigen/station/statistics/real-time-consumption"
                                            consumption_params = {
                                                'stationId': self.station_id,
                                                'loadPath': load['path'],
                                                'smartLoadId': smart_load_id
                                            }
                                            
                                            async with session.get(consumption_url, headers=self.headers, 
                                                                params=consumption_params) as consumption_response:
                                                if consumption_response.status == 200:
                                                    consumption_data = await consumption_response.json()
                                                    if consumption_data.get('code') == 0 and 'data' in consumption_data:
                                                        # Add consumption statistics to the load data
                                                        if consumption_data['data'].get('todayConsumption'):
                                                            load['todayConsumption'] = consumption_data['data'].get('todayConsumption')
                                                        if consumption_data['data'].get('monthConsumption'):
                                                            load['monthConsumption'] = consumption_data['data'].get('monthConsumption')
                                                        if consumption_data['data'].get('lifetimeConsumption'):
                                                            load['lifetimeConsumption'] = consumption_data['data'].get('lifetimeConsumption')
                                                        logger.debug(f"Added consumption data for load {load['name']}: "
                                                                    f"today={load['todayConsumption']}, "
                                                                    f"month={load['monthConsumption']}, "
                                                                    f"lifetime={load['lifetimeConsumption']}")
                                                    else:
                                                        logger.warning(f"Failed to get consumption data for load {load.get('name')}: "
                                                                    f"Invalid response format: {consumption_data}")
                                                else:
                                                    logger.warning(f"Failed to get consumption data for load {load.get('name')}: "
                                                                f"Status {consumption_response.status}")
                                        else:
                                            logger.warning(f"No smartLoadId found for load {load.get('name')} (path: {load['path']})")
                                    else:
                                        logger.warning(f"Invalid response format while getting load details for {load.get('name')}: {load_details}")
                                else:
                                    logger.warning(f"Failed to get smart load details for {load.get('name')}: Status {load_details_response.status}")
                        except Exception as e:
                            logger.error(f"Error fetching consumption data for load {load.get('name')}: {e}")
                            # Continue with next load even if this one fails
                
                self.smart_loads = smart_loads
                return smart_loads
                
    async def set_smart_load_state(self, load_path: int, state: int):
        """
        Set the state of a smart load (on or off).
        
        :param load_path: The path value of the smart load to control
        :param state: 1 to turn on, 0 to turn off
        :return: API response
        """
        if state not in [0, 1]:
            raise ValueError("Smart load state must be 0 (off) or 1 (on)")
            
        await self.ensure_valid_token()
        # Build the URL with query parameters directly in the URL string as shown in the example
        url = f"{self.BASE_URL}device/tp-device/smart-loads/control-mode/manual/switch?stationId={self.station_id}&loadPath={load_path}&manualSwitch={state}"
        
        # Use PATCH request with empty data
        async with aiohttp.ClientSession() as session:
            async with session.patch(url, headers=self.headers) as response:
                logger.debug(f"PATCH request to {url}")
                logger.debug(f"Response status: {response.status}")
                return await response.json()

    async def get_ac_ev_charge_mode(self):
        """
        Get Charge Mode for AC EVSE. E.g.
        :return:
{
"code": 0,
"msg": "success",
"data": {
    "chargeMode": 0,
    "minKeepChargeTime": 5,
    "maxGridChargePower": 7.0,
    "pvEnergyStartPower": 0.0
}
}
        """
        await self.ensure_valid_token()
        url = f"{self.BASE_URL}device/acevse/charge/mode"
        params = {
            'stationId': self.station_id,
            'snCode': self.ac_sn,
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=self.headers, params=params) as response:
                json_response = await response.json()  # Get the full JSON response
                return json_response['data']

    async def get_signals(self):
        await self.ensure_valid_token()
        url = f"{self.BASE_URL}device/sigen/device/crypto/read/batch"
        get_signals_decrypted_payload_template = "\"snCode\":\"2024052302935\",\"addr\":null,\"modeVersion\":null,\"signalIds\":[2008,2009,2929,2930,2941,2931],\"stationSnCode\":\"2024052302935\"}"
        get_signals_decrypted_payload = re.sub(r'"snCode":"\d+"', f'"snCode":"{self.station_id}"', get_signals_decrypted_payload_template)
        get_signals_decrypted_payload = re.sub(r'"stationSnCode":"\d+"', f'"stationSnCode":"{self.station_id}"', get_signals_decrypted_payload)

        encrypted_payload = encrypt_batch_payload(get_signals_decrypted_payload)

        payload = {
            "encryption": encrypted_payload
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=self.headers, json=payload) as response:
                if response.status == 200:
                    response_json = await response.json()
                    return decrypt_batch_payload(response_json.get("encryption", {}))
                else:
                    raise Exception(f"Failed to get signals. Response code: {response.status}, Response: {await response.text()}")

def encrypt_password(password):
    key = "sigensigensigenp"
    iv = "sigensigensigenp"

    cipher = AES.new(key.encode('utf-8'), AES.MODE_CBC, iv.encode('latin1'))
    encrypted = cipher.encrypt(pad(password.encode('utf-8'), AES.block_size))
    return base64.b64encode(encrypted).decode('utf-8')

def encrypt_batch_payload(plain_text):
    # Ensure the key length is 16 bytes long
    key = batch_key.encode('utf-8')
    key = pad(key, 16)[:16]

    iv = b'\xe4\xf5\xc4>\x17%\x18\r\xa2{\x03\xed\xf5\n\xaf\xa7'

    # Create AES cipher instance
    cipher = AES.new(key, AES.MODE_CBC, iv)

    # Pad the plain text
    plain_bytes = pad(plain_text.encode('utf-8'), AES.block_size)

    # Encrypt the data
    encrypted_bytes = cipher.encrypt(plain_bytes)

    # Combine IV and encrypted data
    encrypted_data = iv + encrypted_bytes

    # Encode the encrypted data with base64
    encrypted_data_base64 = base64.b64encode(encrypted_data)

    return encrypted_data_base64.decode('utf-8')

def decrypt_batch_payload(encrypted_data):
    # Ensure the key length is 16, 24, or 32 bytes long
    key = batch_key.encode('utf-8')
    key = pad(key, 16)[:16]

    # Decode the base64 encoded data
    encrypted_data = base64.b64decode(encrypted_data)

    # Extract the IV from the beginning
    iv = encrypted_data[:AES.block_size]

    # Extract the encrypted data
    encrypted_bytes = encrypted_data[AES.block_size:]

    # Create AES cipher instance
    cipher = AES.new(key, AES.MODE_CBC, iv)

    # Decrypt and unpad the data
    decrypted_bytes = unpad(cipher.decrypt(encrypted_bytes), AES.block_size)
    return decrypted_bytes.decode('utf-8')


# Example usage:
# import asyncio
# sigen = Sigen(username="your_username", password="your_password", region="us")
# asyncio.run(sigen.async_initialize())
# asyncio.run(sigen.fetch_station_info())
# print(asyncio.run(sigen.get_energy_flow()))
# print(asyncio.run(sigen.get_operational_mode()))
# print(asyncio.run(sigen.set_operational_mode_sigen_ai_mode()))
# print(asyncio.run(sigen.set_operational_mode_maximum_self_powered()))
# print(asyncio.run(sigen.set_operational_mode_tou()))
# print(asyncio.run(sigen.set_operational_mode_fully_fed_to_grid()))