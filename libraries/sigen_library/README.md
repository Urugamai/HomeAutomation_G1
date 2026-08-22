## Sigen
_Unofficial package for reading and writing data to and from Sigenergy inverters via cloud APIs._

**Version 3.0.0** - Updated to support v3 app APIs for modes and smart loads.

> [!IMPORTANT]  
> This repository is only sporadically maintained.  Breaking API changes will be maintained on a best efforts basis.
>
> Collaborators are welcome, as are PRs for enhancements.
>
> Bug reports unrelated to API changes may not get the attention you want. 


### Installation
```bash
pip install sigen
```

### Usage

```python
from sigen import Sigen

# username and password you use in the mySigen app.
# Region is Europe (eu) / Asia-Pacific (apac) /
# Middle East & Africa (eu) / Chinese Mainland (cn) / Unitest States (us)
sigen = Sigen(username="your_username", password="your_password", region="eu")

# Initialize the Sigen instance
await sigen.async_initialize()

# Read data
print(await sigen.fetch_station_info())
print(await sigen.get_energy_flow())
print(await sigen.get_operational_mode())

# Set default modes
print(await sigen.set_operational_mode_sigen_ai_mode())
print(await sigen.set_operational_mode_maximum_self_powered())
print(await sigen.set_operational_mode_tou())
print(await sigen.set_operational_mode_fully_fed_to_grid())

# Set custom modes (if available)
print(await sigen.set_operational_mode_summer_50kwh())

# Get and control smart loads
smart_loads = await sigen.get_smart_loads()
for load in smart_loads:
    print(f"Smart Load: {load['name']} - Power: {load['valueWithUnit']}")

# Control smart loads (using path value)
print(await sigen.set_smart_load_state(1, 1))  # Turn on smart load with path 1
print(await sigen.set_smart_load_state(1, 0))  # Turn off smart load with path 1

# Or use convenient dynamic methods (generated from available smart loads)
print(await sigen.enable_smart_load_immersion())   # Turn on
print(await sigen.disable_smart_load_immersion())  # Turn off

```

Full example:
```python
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

    sigen = Sigen(username=username, password=password)

    # Initialize the Sigen instance
    await sigen.async_initialize()

    # Fetch and log station info
    logger.info("Fetching station info...")
    station_info = await sigen.fetch_station_info()
    logger.info("Station Info:")
    logger.info(f"Station ID: {station_info['stationId']}")
    logger.info(f"Has PV: {station_info['hasPv']}")
    logger.info(f"Has EV: {station_info['hasEv']}")
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
    logger.info(f"Load Power: {energy_flow['loadPower']} kW")
    logger.info(f"Battery Power: {energy_flow['batteryPower']} kW")
    logger.info(f"Battery SOC: {energy_flow['batterySoc']}%")

    # Fetch and log current operational mode
    logger.info("\nFetching current operational mode...")
    current_mode = await sigen.get_operational_mode()
    logger.info(f"Current Operational Mode: {current_mode}")

    # Change operational mode
    # For default modes - using dynamic methods
    # logger.info("\nSetting operational mode to 'Fully Fed to Grid'...")
    # response = await sigen.set_operational_mode_fully_fed_to_grid()
    # logger.info(f"Response: {response}")
    
    # For default modes - using direct method
    # logger.info("\nSetting operational mode to TOU (value=2)...")
    # response = await sigen.set_operational_mode(2, -1)  # -1 for default modes
    # logger.info(f"Response: {response}")
    
    # For custom modes - using dynamic methods
    # logger.info("\nSetting operational mode to 'Summer 40kWh'...")
    # response = await sigen.set_operational_mode_summer_40kwh()
    # logger.info(f"Response: {response}")
    
    # For custom modes - using direct method with profile ID
    # logger.info("\nSetting operational mode to custom profile ID 4326...")
    # response = await sigen.set_operational_mode(9, 4326)  # 9 for custom modes with profile ID
    # logger.info(f"Response: {response}")
    # logger.info(f"Response: {response}")

    # logger.info("\nFetching current operational mode...")
    # current_mode = await sigen.get_operational_mode()
    # logger.info(f"Current Operational Mode: {current_mode}")


if __name__ == "__main__":
    asyncio.run(main())
```

Example output including the new features:
```bash
2025-06-25 18:25:16 INFO Fetching station info...
2025-06-25 18:25:16 INFO Station ID: 2024052302935
2025-06-25 18:25:16 INFO Has PV: True
2025-06-25 18:25:16 INFO Has EV: False
2025-06-25 18:25:16 INFO Has AC Charger: True
2025-06-25 18:25:16 INFO On Grid: True
2025-06-25 18:25:16 INFO PV Capacity: 10.3 kW
2025-06-25 18:25:16 INFO Battery Capacity: 8.06 kWh

2025-06-25 18:25:17 INFO Fetching all available operational modes...

2025-06-25 18:25:17 INFO Default Working Modes:
2025-06-25 18:25:17 INFO   - Sigen AI Mode (value: 1)
2025-06-25 18:25:17 INFO   - Maximum Self-Powered (value: 0)
2025-06-25 18:25:17 INFO   - TOU (value: 2)
2025-06-25 18:25:17 INFO   - Fully Fed to Grid (value: 5)
2025-06-25 18:25:17 INFO   - Remote EMS Mode (value: 7)

2025-06-25 18:25:17 INFO Custom Energy Profile Items:
2025-06-25 18:25:17 INFO   - Summer 50kWh (profileId: 3126, value: 9)
2025-06-25 18:25:17 INFO   - Storm Ready (profileId: 3939, value: 9)
2025-06-25 18:25:17 INFO   - Summer 40kWh (profileId: 4326, value: 9)
2025-06-25 18:25:17 INFO   - Summer 30kWh (profileId: 4328, value: 9)

2025-06-25 18:25:17 INFO Current Operational Mode: TOU

2025-06-25 18:25:19 INFO --------- Smart Loads Functionality ---------
2025-06-25 18:25:19 INFO Fetching smart loads...
2025-06-25 18:25:19 INFO Found 1 smart loads:
2025-06-25 18:25:19 INFO   - Name: Immersion
2025-06-25 18:25:19 INFO     Path: 1
2025-06-25 18:25:19 INFO     Power: 0.00 kW
2025-06-25 18:25:19 INFO     Current state: ON
2025-06-25 18:25:19 INFO     Enable method: sigen.enable_smart_load_immersion()
2025-06-25 18:25:19 INFO     Disable method: sigen.disable_smart_load_immersion()
```
