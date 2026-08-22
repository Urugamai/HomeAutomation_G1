import pytest
from aioresponses import aioresponses
from sigen import Sigen, create_dynamic_methods


@pytest.fixture
def sigen_instance():
    return Sigen(username="mock_user", password="mock_password")

@pytest.mark.asyncio
async def test_get_access_token(sigen_instance):
    with aioresponses() as m:
        m.post('https://api-eu.sigencloud.com/auth/oauth/token', payload={
            "data": {
                "access_token": "mock_access_token",
                "refresh_token": "mock_refresh_token",
                "expires_in": 3600
            }
        })

        await sigen_instance.get_access_token()

        assert sigen_instance.access_token == "mock_access_token"
        assert sigen_instance.refresh_token == "mock_refresh_token"
        assert sigen_instance.headers['Authorization'] == f'Bearer mock_access_token'

@pytest.mark.asyncio
async def test_fetch_station_info(sigen_instance):
    with aioresponses() as m:
        # Mock the token fetch
        m.post('https://api-eu.sigencloud.com/auth/oauth/token', payload={
            "data": {
                "access_token": "mock_access_token",
                "refresh_token": "mock_refresh_token",
                "expires_in": 3600
            }
        })
        await sigen_instance.get_access_token()

        # Mock the station info fetch
        m.get('https://api-eu.sigencloud.com/device/owner/station/home', payload={
            "data": {
                "stationId": 12345,
                "hasPv": True,
                "hasEv": False,
                "onGrid": True,
                "pvCapacity": 10.3,
                "batteryCapacity": 8.06
            }
        })

        station_info = await sigen_instance.fetch_station_info()

        assert sigen_instance.station_id == 12345
        assert station_info['stationId'] == 12345
        assert station_info['hasPv'] == True
        assert station_info['pvCapacity'] == 10.3

@pytest.mark.asyncio
async def test_get_energy_flow(sigen_instance):
    with aioresponses() as m:
        # Mock the token fetch
        m.post('https://api-eu.sigencloud.com/auth/oauth/token', payload={
            "data": {
                "access_token": "mock_access_token",
                "refresh_token": "mock_refresh_token",
                "expires_in": 3600
            }
        })
        await sigen_instance.get_access_token()

        # Mock the station info fetch
        m.get('https://api-eu.sigencloud.com/device/owner/station/home', payload={
            "data": {
                "stationId": 12345,
                "hasPv": True,
                "hasEv": False,
                "onGrid": True,
                "pvCapacity": 10.3,
                "batteryCapacity": 8.06
            }
        })
        await sigen_instance.fetch_station_info()

        # Mock the energy flow fetch
        m.get('https://api-eu.sigencloud.com/device/sigen/station/energyflow?id=12345', payload={
            "data": {
                "pvDayNrg": 30.43,
                "pvPower": 5.7,
                "buySellPower": 5.0,
                "evPower": 0.0,
                "acPower": 0.0,
                "loadPower": 0.5,
                "heatPumpPower": 0.0,
                "batteryPower": 0.2,
                "batterySoc": 93.8
            }
        })

        energy_flow = await sigen_instance.get_energy_flow()

        assert energy_flow['pvDayNrg'] == 30.43
        assert energy_flow['pvPower'] == 5.7
        assert energy_flow['loadPower'] == 0.5
        assert energy_flow['batterySoc'] == 93.8

@pytest.mark.asyncio
async def test_get_operational_mode(sigen_instance):
    with aioresponses() as m:
        # Mock the token fetch
        m.post('https://api-eu.sigencloud.com/auth/oauth/token', payload={
            "data": {
                "access_token": "mock_access_token",
                "refresh_token": "mock_refresh_token",
                "expires_in": 3600
            }
        })
        await sigen_instance.get_access_token()

        # Mock the station info fetch
        m.get('https://api-eu.sigencloud.com/device/owner/station/home', payload={
            "data": {
                "stationId": 12345,
                "hasPv": True,
                "hasEv": False,
                "onGrid": True,
                "pvCapacity": 10.3,
                "batteryCapacity": 8.06
            }
        })
        await sigen_instance.fetch_station_info()

        # Mock the operational mode fetch
        m.get('https://api-eu.sigencloud.com/device/setting/operational/mode/12345', payload={
            "data": 2
        })
        m.get('https://api-eu.sigencloud.com/device/sigen/station/operational/mode/v/12345', payload={
            "data": [
                {
                    "label": "Sigen AI Mode",
                    "sortOrder": 0,
                    "remarks": "",
                    "value": "1"
                },
                {
                    "label": "Maximum Self-Powered",
                    "sortOrder": 0,
                    "remarks": "",
                    "value": "0"
                },
                {
                    "label": "TOU",
                    "sortOrder": 0,
                    "remarks": "",
                    "value": "2"
                },
                {
                    "label": "Fully Fed to Grid",
                    "sortOrder": 0,
                    "remarks": "",
                    "value": "5"
                }
            ]
        })

        operational_mode = await sigen_instance.get_operational_mode()

        assert operational_mode == "TOU"

@pytest.mark.asyncio
async def test_set_operational_mode(sigen_instance):
    with aioresponses() as m:
        # Mock the token fetch
        m.post('https://api-eu.sigencloud.com/auth/oauth/token', payload={
            "data": {
                "access_token": "mock_access_token",
                "refresh_token": "mock_refresh_token",
                "expires_in": 3600
            }
        })
        await sigen_instance.get_access_token()

        # Mock the station info fetch
        m.get('https://api-eu.sigencloud.com/device/owner/station/home', payload={
            "data": {
                "stationId": 12345,
                "hasPv": True,
                "hasEv": False,
                "onGrid": True,
                "pvCapacity": 10.3,
                "batteryCapacity": 8.06
            }
        })
        await sigen_instance.fetch_station_info()

        # Mock the operational mode fetch
        m.get('https://api-eu.sigencloud.com/device/sigen/station/operational/mode/v/12345', payload={
            "data": [
                {
                    "label": "Sigen AI Mode",
                    "sortOrder": 0,
                    "remarks": "",
                    "value": "1"
                },
                {
                    "label": "Maximum Self-Powered",
                    "sortOrder": 0,
                    "remarks": "",
                    "value": "0"
                },
                {
                    "label": "TOU",
                    "sortOrder": 0,
                    "remarks": "",
                    "value": "2"
                },
                {
                    "label": "Fully Fed to Grid",
                    "sortOrder": 0,
                    "remarks": "",
                    "value": "5"
                }
            ]
        })

        await sigen_instance.fetch_operational_modes()

        # Mock the set operational mode
        m.put('https://api-eu.sigencloud.com/device/setting/operational/mode/', payload={
            "code": 0,
            "msg": "success"
        })

        response = await sigen_instance.set_operational_mode(5)

        assert response['code'] == 0
        assert response['msg'] == "success"

@pytest.mark.asyncio
async def test_dynamic_methods(sigen_instance):
    with aioresponses() as m:
        # Mock the token fetch
        m.post('https://api-eu.sigencloud.com/auth/oauth/token', payload={
            "data": {
                "access_token": "mock_access_token",
                "refresh_token": "mock_refresh_token",
                "expires_in": 3600
            }
        })
        await sigen_instance.get_access_token()

        # Mock the station info fetch
        m.get('https://api-eu.sigencloud.com/device/owner/station/home', payload={
            "data": {
                "stationId": 12345,
                "hasPv": True,
                "hasEv": False,
                "onGrid": True,
                "pvCapacity": 10.3,
                "batteryCapacity": 8.06
            }
        })
        await sigen_instance.fetch_station_info()
        # Mock the operational mode fetch
        m.get('https://api-eu.sigencloud.com/device/sigen/station/operational/mode/v/12345', payload={
            "data": [
                {
                    "label": "Sigen AI Mode",
                    "sortOrder": 0,
                    "remarks": "",
                    "value": "1"
                },
                {
                    "label": "Maximum Self-Powered",
                    "sortOrder": 0,
                    "remarks": "",
                    "value": "0"
                },
                {
                    "label": "TOU",
                    "sortOrder": 0,
                    "remarks": "",
                    "value": "2"
                },
                {
                    "label": "Fully Fed to Grid",
                    "sortOrder": 0,
                    "remarks": "",
                    "value": "5"
                }
            ]
        })

        await sigen_instance.fetch_operational_modes()

        create_dynamic_methods(sigen_instance)

        # Mock the set operational mode
        m.put('https://api-eu.sigencloud.com/device/setting/operational/mode/', payload={
            "code": 0,
            "msg": "success"
        })

        response = await sigen_instance.set_operational_mode_fully_fed_to_grid()

        assert response['code'] == 0
        assert response['msg'] == "success"