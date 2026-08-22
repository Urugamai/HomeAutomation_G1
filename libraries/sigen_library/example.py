import logging
import os
import asyncio
from sigen import Sigen

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def main():
    # Read username and password from environment variables
    username = os.getenv('SIGEN_USERNAME')
    password = os.getenv('SIGEN_PASSWORD')

    if not username or not password:
        logging.error("Environment variables SIGEN_USERNAME and SIGEN_PASSWORD must be set")
        return

    # username and password you use in the mySigen app.
    # Region is Europe (eu) / Asia-Pacific (apac) /
    # Middle East & Africa (eu) / Chinese Mainland (cn) / Unitest States (us)
    sigen = Sigen(username=username, password=password, region="eu")

    # Initialize the Sigen instance
    await sigen.async_initialize()

    # Fetch and log station info
    logger.info("Fetching station info...")
    station_info = await sigen.fetch_station_info()
    logger.info("Station Info:")
    logger.info(f"Station ID: {station_info['stationId']}")
    logger.info(f"Has PV: {station_info['hasPv']}")
    logger.info(f"Has EV: {station_info['hasEv']}")
    logger.info(f"Has AC Charger: {station_info['hasAcCharger']}")
    logger.info(f"AC Charger Serial Numbers: {station_info['acSnList']}")
    logger.info(f"On Grid: {station_info['onGrid']}")
    logger.info(f"PV Capacity: {station_info['pvCapacity']} kW")
    logger.info(f"Battery Capacity: {station_info['batteryCapacity']} kWh")

    # Fetch and log energy flow info
    logger.info("\nFetching energy flow info...")
    energy_flow = await sigen.get_energy_flow()
    logger.info("Energy Flow Info:")
    logger.info(f"PV Day Energy: {energy_flow['pvDayNrg']} kWh")
    logger.info(f"PV Power: {energy_flow['pvPower']} kW")
    logger.info(f"Buy/Sell Power: {energy_flow['buySellPower']} kW")
    logger.info(f"EV Power: {energy_flow['evPower']} kW")
    logger.info(f"AC Power: {energy_flow['acPower']} kW")
    logger.info(f"acRunStatus: {energy_flow['acRunStatus']} ")
    logger.info(f"Load Power: {energy_flow['loadPower']} kW")
    logger.info(f"Battery Power: {energy_flow['batteryPower']} kW")
    logger.info(f"Battery SOC: {energy_flow['batterySoc']}%")

    # Fetch and log all available operational modes
    logger.info("\nFetching all available operational modes...")
    all_modes = await sigen.get_operational_modes()
    
    # Display default modes
    logger.info("Default Working Modes:")
    for mode in all_modes['defaultWorkingModes']:
        logger.info(f"  - {mode['label']} (value: {mode['value']})")
    
    # Display custom modes
    logger.info("\nCustom Energy Profile Items:")
    for mode in all_modes['energyProfileItems']:
        logger.info(f"  - {mode['name']} (profileId: {mode['profileId']}, value: {mode['value']})")
    
    # Fetch and log current operational mode
    logger.info("\nFetching current operational mode...")
    current_mode = await sigen.get_operational_mode()
    logger.info(f"Current Operational Mode: {current_mode}")


    soc_signals = await sigen.get_signals()
    logger.info(f"Current soc_signals: {soc_signals}")

    ac_ev_charge_mode = await sigen.get_ac_ev_charge_mode()
    logger.info(f"Current ac_ev_charge_mode: {ac_ev_charge_mode}")

    await sigen.get_ac_ev_current()

    logger.info(f"ac_ev_max_dlm_status: {sigen.ac_ev_dlm_status}")
    logger.info(f"ac_ev_last_set_current: {sigen.ac_ev_last_set_current}A. (Max: {sigen.ac_ev_max_current}A)")

    await sigen.set_ac_ev_dlm_status(0)

    await sigen.get_ac_ev_current()
    logger.info(f"ac_ev_max_dlm_status: {sigen.ac_ev_dlm_status}")
    logger.info(f"ac_ev_last_set_current: {sigen.ac_ev_last_set_current}A. (Max: {sigen.ac_ev_max_current}A)")

    await sigen.set_ac_ev_current(30)

    # await sigen.set_ac_ev_dlm_status(1)
    response = await sigen.get_ac_ev_current()
    # logger.info(f"response: {response}")
    logger.info(f"ac_ev_max_dlm_status: {sigen.ac_ev_dlm_status}")
    logger.info(f"ac_ev_last_set_current: {sigen.ac_ev_last_set_current}A. (Max: {sigen.ac_ev_max_current}A)")

    # Example of setting a default mode directly with mode value and profile_id=-1
    # logger.info("\nSetting operational mode to 'Fully Fed to Grid' (value=5)...")
    # response = await sigen.set_operational_mode(5, -1)
    # logger.info(f"Response: {response}")
    
    # Example of setting a custom mode directly with mode=9 and profile_id
    # logger.info("\nSetting operational mode to custom mode with profileId=4326...")
    # response = await sigen.set_operational_mode(9, 4326)
    # logger.info(f"Response: {response}")
    
    # Or use the dynamically created methods for convenience
    # For default modes:
    # logger.info("\nSetting operational mode to 'Sigen AI Mode'...")
    # response = await sigen.set_operational_mode_sigen_ai_mode()
    # logger.info(f"Response: {response}")
    
    # logger.info("\nSetting operational mode to 'TOU'...")
    # response = await sigen.set_operational_mode_tou()
    # logger.info(f"Response: {response}")
    
    # For custom modes:
    # logger.info("\nSetting operational mode to 'Summer 40kWh'...")
    # response = await sigen.set_operational_mode_summer_40kwh()
    # logger.info(f"Response: {response}")
    
    # After setting a mode, get the current mode to verify
    # logger.info("\nFetching current operational mode after change...")
    # current_mode = await sigen.get_operational_mode()
    # logger.info(f"Current Operational Mode: {current_mode}")
    
    # Demo Smart Loads functionality
    logger.info("\n--------- Smart Loads Functionality ---------")
    
    # Get all smart loads
    logger.info("Fetching smart loads...")
    smart_loads = await sigen.get_smart_loads()
    
    # Display smart loads
    logger.info(f"Found {len(smart_loads)} smart loads:")
    for load in smart_loads:
        logger.info(f"  - Name: {load['name']}")
        logger.info(f"    Path: {load['path']}")
        logger.info(f"    Power: {load['valueWithUnit']}")
        logger.info(f"    monthConsumption: {load['monthConsumption']}")
        logger.info(f"    todayConsumption: {load['todayConsumption']}")
        logger.info(f"    lifetimeConsumption: {load['lifetimeConsumption']}")
        logger.info(f"    Current state: {'ON' if load['manualSwitch'] == 1 else 'OFF'}")
        
        # Show dynamically created method names for this smart load
        safe_name = load['name'].lower().replace(' ', '_').replace('-', '_')
        logger.info(f"    Enable method: sigen.enable_smart_load_{safe_name}()")
        logger.info(f"    Disable method: sigen.disable_smart_load_{safe_name}()")
    
    # Example of using the dynamic methods (commented out to prevent accidental execution)
    # if smart_loads and len(smart_loads) > 0:
    #     first_load = smart_loads[0]
    #     safe_name = first_load['name'].lower().replace(' ', '_').replace('-', '_')
        
    #     # Get the dynamically created method names
    #     enable_method_name = f"enable_smart_load_{safe_name}"
    #     disable_method_name = f"disable_smart_load_{safe_name}"
        
    #     # Check if the methods exist
    #     if hasattr(sigen, disable_method_name) and hasattr(sigen, enable_method_name):
    #         # Turn off using dynamic method
    #         logger.info(f"\nDisabling smart load: {first_load['name']} using {disable_method_name}()...")
    #         disable_method = getattr(sigen, disable_method_name)
    #         response = await disable_method()
    #         logger.info(f"Response: {response}")
            
    #         # Wait a moment before turning back on
    #         logger.info("Waiting 5 seconds...")
    #         await asyncio.sleep(5)
            
    #         # Turn back on using dynamic method
    #         logger.info(f"Enabling smart load: {first_load['name']} using {enable_method_name}()...")
    #         enable_method = getattr(sigen, enable_method_name)
    #         response = await enable_method()
    #         logger.info(f"Response: {response}")


if __name__ == "__main__":
    asyncio.run(main())