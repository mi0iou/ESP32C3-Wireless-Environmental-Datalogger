# ESP32-C3 Environmental Datalogger

A wireless environmental monitoring station built with the ESP32-C3 microcontroller. Logs temperature, humidity, pressure, gas resistance, ambient light, and battery voltage with a built-in web interface for real-time monitoring and data download.

## Features

- 📊 **Multi-sensor monitoring**: BME680 (temperature, humidity, pressure, gas) + VEML7700 (light)
- 📡 **WiFi web interface**: Access data from any browser on your network
- 💾 **Automatic data logging**: Daily CSV files with 7-day rotation
- 🔋 **Battery monitoring**: Real-time voltage tracking with charging detection
- ⚡ **Low power**: Optimized for battery operation (<50mA)
- 📥 **Easy data export**: Download log files directly from web interface
- 🔄 **Auto-reconnect**: Recovers from WiFi disconnections automatically

## Hardware Requirements

### Components

| Component | Quantity | Notes |
|-----------|----------|-------|
| ESP32-C3 Super Mini | 1 | or other ESP32C3 board |
| BME680 Sensor Module | 1 | I2C address: 0x76 |
| VEML7700 Light Sensor | 1 | I2C address: 0x10 |
| 4.7kΩ Resistors | 2 | I2C pull-ups (SDA, SCL) |
| 10kΩ Resistors | 2 | Voltage divider for battery monitoring |
| LiPo Battery | 1 | 1000mAh+ recommended |
| Breadboard/PCB | 1 | For prototyping or permanent build |
| Jumper wires | Various | |

### Pin Connections

| ESP32-C3 Pin | Connection | Notes |
|--------------|------------|-------|
| GPIO 20 | SDA (both sensors) | I2C data line |
| GPIO 21 | SCL (both sensors) | I2C clock line |
| GPIO 3 | Battery voltage divider | ADC for voltage monitoring |
| 3.3V | Sensor VCC + Pull-ups | Power rail |
| GND | Common ground | Ground rail |

### Circuit Notes

- **I2C Pull-ups**: 4.7kΩ resistors from SDA/SCL to 3.3V are required
- **Voltage Divider**: Two 10kΩ resistors in series between Battery+ and GND, tap point to GPIO3
- **Shared I2C Bus**: Both sensors use the same SDA/SCL lines

See `Schematic.png` and `Breadboard.png` for detailed wiring diagrams.

## Software Requirements

### Prerequisites

- **MicroPython** firmware for ESP32-C3 (v1.20 or later)
- **bme680.py** required library (copy included in repo you can [Download here](https://github.com/robert-hh/BME680-Micropython)
- USB cable for programming
- Terminal program (Thonny or similar)
- project includes a custom VEML7700 driver.

## Installation

### 1. Flash MicroPython

This may be done using Thonny's "Configure interpreter" option

### 2. Configure WiFi

Edit the main program to include your WiFi credentials:
```python
SSID = "YourNetworkName"
PASSWORD = "YourPassword"
```
Save the main program as "main.py"

### 4. Upload Main Script and BME680 driver
Upload `main.py` and "bme680.py" to the ESP32-C3

### 5. Reboot

Reset the ESP32-C3. It will:
1. Connect to WiFi
2. Sync time via NTP
3. Initialize sensors
4. Start logging and web server

Check the serial console for the IP address.

## Usage

### Accessing the Web Interface

Open a browser and navigate to:
```
http://<ESP32-C3-IP-ADDRESS>

OR 

http://breadboard.local
```

### Web Interface Pages

**Home Page** (`/`)
- Real-time sensor readings
- Battery status with color coding
- Light level classification
- Auto-refreshes every 60 seconds

**Log Files** (`/logs`)
- Browse all daily log files
- Download CSV files for analysis
- Delete old logs (current day protected)
- View file sizes

### Log File Format

CSV files are created daily with the format: `YYYY-MM-DD.log`

Example: `2025-12-27.log`

**Columns:**
```csv
Time,Temp(C),Pressure(hPa),Humidity(%),Gas(Ohm),Light(lux),Battery(V)
14:30:15, 22.45, 1013.25, 45.30, 125000, 450.5, 3.85
```

### Configuration Options

Edit these variables in the code to customize:

```python
LOG_INTERVAL = 60          # Logging interval in seconds
MAX_LOG_FILES = 7          # Number of daily logs to keep
UTC_OFFSET = 0             # Timezone offset in seconds
VOLTAGE_DIVIDER_RATIO = 2.0  # Adjust for your resistors
BATTERY_ENABLED = True     # Enable/disable battery monitoring
VEML7700_ENABLED = True    # Enable/disable light sensor
```


## Technical Specifications

- **Microcontroller**: ESP32-C3 (RISC-V @ 160MHz)
- **WiFi**: 802.11 b/g/n (2.4GHz)
- **I2C Frequency**: 100kHz
- **ADC Resolution**: 12-bit
- **Power Consumption**: <50mA typical
- **Battery Life**: 2-3 days (1000mAh LiPo, 60s logging interval)
- **Flash Storage**: Supports weeks of logs
- **Logging Rate**: Configurable (default 60 seconds)
- **Web Server**: Non-blocking, threaded operation

## Project Structure

```
esp32c3-datalogger/
├── ESP32C3Datalogger.py # Main application code
├── bme680.py            # BME680 sensor library
├── README.md            # This file
├── Schematic.png        # Circuit schematic
├── BreadBoard.png       # Breadboard layout
├── CurrentReadings.png  # Screenshot of main web page
├── LogFiles.png         # Screenshot of file management web page
```

## Possible Future Enhancements

- [ ] MQTT support for Home Assistant
- [ ] Historical data graphing on web interface
- [ ] Email/SMS alerts for thresholds
- [ ] OTA firmware updates
- [ ] Deep sleep mode for extended battery life
- [ ] SD card support for long-term storage
- [ ] Export to cloud services

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## Acknowledgments

- VEML7700 driver based on work by Joseph Hopfmüller and Christophe Rousseau
- BME680 library from Robert Hammelrath
- Thanks to the MicroPython community
- Thanks to Espressif for making such great SoC's
