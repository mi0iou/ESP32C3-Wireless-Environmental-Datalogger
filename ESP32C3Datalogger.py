import network, socket, gc, time, ntptime, os, _thread, machine
from machine import Pin, I2C, ADC
import bme680

# --- Config ---
SSID = "XXXXXXXX"
PASSWORD = "XXXXXXXX"
MAX_LOG_FILES = 7  # Keep 1 week of daily logs
LOG_INTERVAL = 60  # seconds
UTC_OFFSET = 0  # Adjust for your timezone (e.g., 3600 for UTC+1)

# Battery monitoring config
BATTERY_PIN = 3  # GPIO3 = ADC1 Channel 3
VOLTAGE_DIVIDER_RATIO = 2.0  # Adjust based on your resistor values (R1+R2)/R2
BATTERY_ENABLED = True  # Set to False to disable battery monitoring

# VEML7700 config
VEML7700_ENABLED = True  # Set to False to disable light sensor
VEML7700_ADDRESS = 0x10  # Default I2C address

# Thread safety
sensor_lock = _thread.allocate_lock()

# --- Wi-Fi ---
def connect_wifi(ssid, password, max_retries=5, timeout=15):
    wlan = network.WLAN(network.STA_IF)
    
    # Force cleanup of any existing connection state
    try:
        wlan.active(False)
        time.sleep(1)
    except:
        pass
    
    wlan.active(True)
    time.sleep(1)
    
    # Disconnect any existing connection
    try:
        wlan.disconnect()
        time.sleep(1)
    except:
        pass
    
    wlan.config(dhcp_hostname="BreadBoard")
    
    for attempt in range(1, max_retries + 1):
        print("Attempt {} of {}...".format(attempt, max_retries))
        try:
            wlan.connect(ssid, password)
            for t in range(timeout):
                if wlan.isconnected():
                    print("Connected to WiFi")
                    print("IP:", wlan.ifconfig()[0])
                    return wlan
                time.sleep(1)
                print("  waiting... ({}/{})".format(t + 1, timeout))
        except Exception as e:
            print("  Connection error:", e)
            
        print("  Timeout on attempt", attempt)
        try:
            wlan.disconnect()
        except:
            pass
        time.sleep(2)
        
    print("Failed to connect after {} retries.".format(max_retries))
    return None

def check_wifi_reconnect(wlan, ssid, password):
    """Check WiFi connection and reconnect if needed"""
    if not wlan.isconnected():
        print("WiFi disconnected, attempting reconnection...")
        wlan.connect(ssid, password)
        for _ in range(30):  # 30 second timeout
            if wlan.isconnected():
                print("Reconnected to WiFi")
                return True
            time.sleep(1)
        print("Reconnection failed")
        return False
    return True

# --- Time ---
def sync_time():
    try:
        ntptime.settime()
        print("Time synchronized via NTP")
    except Exception as e:
        print("NTP sync failed:", e)

def timestamp():
    tm = time.localtime(time.time() + UTC_OFFSET)
    return "{:02d}:{:02d}:{:02d}".format(tm[3], tm[4], tm[5])

def date_str():
    tm = time.localtime(time.time() + UTC_OFFSET)
    return "{:04d}-{:02d}-{:02d}".format(tm[0], tm[1], tm[2])

# --- Battery Monitoring ---
def init_battery_monitor():
    """Initialize ADC for battery voltage monitoring"""
    if not BATTERY_ENABLED:
        return None
    try:
        adc = ADC(Pin(BATTERY_PIN))
        adc.atten(ADC.ATTN_11DB)  # Full range: 0-3.3V (measures up to ~3.6V)
        adc.width(ADC.WIDTH_12BIT)  # 12-bit resolution (0-4095)
        print("Battery monitor initialized on GPIO{}".format(BATTERY_PIN))
        return adc
    except Exception as e:
        print("Battery monitor init failed:", e)
        return None

def read_battery_voltage(adc):
    """Read battery voltage with averaging"""
    if adc is None:
        return None
    try:
        # Take 10 readings and average to reduce noise
        total = 0
        for _ in range(10):
            total += adc.read()
            time.sleep_ms(10)
        
        avg_reading = total / 10
        
        # Convert ADC reading to voltage
        # ESP32-C3 ADC: 0-4095 represents 0-3.3V (with 11dB attenuation)
        voltage = (avg_reading / 4095.0) * 3.3 * VOLTAGE_DIVIDER_RATIO
        
        return voltage
    except Exception as e:
        print("Battery read error:", e)
        return None

# --- VEML7700 Light Sensor ---
class VEML7700:
    """VEML7700 light sensor driver - based on working reference implementation"""
    
    def __init__(self, i2c, address=0x10, it=100, gain=1/8):
        self.address = address
        self.i2c = i2c
        
        # Configuration values for different integration times and gains
        # Format: confValues[integration_time][gain] = bytearray([low_byte, high_byte])
        confValues = {
            25:  {1/8: bytearray([0x00, 0x13]), 1/4: bytearray([0x00, 0x1B]), 1: bytearray([0x00, 0x01]), 2: bytearray([0x00, 0x0B])},
            50:  {1/8: bytearray([0x00, 0x12]), 1/4: bytearray([0x00, 0x1A]), 1: bytearray([0x00, 0x02]), 2: bytearray([0x00, 0x0A])},
            100: {1/8: bytearray([0x00, 0x10]), 1/4: bytearray([0x00, 0x18]), 1: bytearray([0x00, 0x00]), 2: bytearray([0x00, 0x08])},
            200: {1/8: bytearray([0x40, 0x10]), 1/4: bytearray([0x40, 0x18]), 1: bytearray([0x40, 0x00]), 2: bytearray([0x40, 0x08])},
            400: {1/8: bytearray([0x80, 0x10]), 1/4: bytearray([0x80, 0x18]), 1: bytearray([0x80, 0x00]), 2: bytearray([0x80, 0x08])},
            800: {1/8: bytearray([0xC0, 0x10]), 1/4: bytearray([0xC0, 0x18]), 1: bytearray([0xC0, 0x00]), 2: bytearray([0xC0, 0x08])}
        }
        
        # Gain values (lux per count) for different integration times and gains
        gainValues = {
            25:  {1/8: 1.8432, 1/4: 0.9216, 1: 0.2304, 2: 0.1152},
            50:  {1/8: 0.9216, 1/4: 0.4608, 1: 0.1152, 2: 0.0576},
            100: {1/8: 0.4608, 1/4: 0.2304, 1: 0.0288, 2: 0.0144},
            200: {1/8: 0.2304, 1/4: 0.1152, 1: 0.0288, 2: 0.0144},
            400: {1/8: 0.1152, 1/4: 0.0576, 1: 0.0144, 2: 0.0072},
            800: {1/8: 0.0876, 1/4: 0.0288, 1: 0.0072, 2: 0.0036}
        }
        
        # Get configuration for selected integration time and gain
        confValuesForIt = confValues.get(it)
        gainValuesForIt = gainValues.get(it)
        
        if confValuesForIt is not None and gainValuesForIt is not None:
            confValueForGain = confValuesForIt.get(gain)
            gainValueForGain = gainValuesForIt.get(gain)
            if confValueForGain is not None and gainValueForGain is not None:
                self.confValues = confValueForGain
                self.gain = gainValueForGain
            else:
                raise ValueError('Wrong gain value. Use 1/8, 1/4, 1, 2')
        else:
            raise ValueError('Wrong integration time value. Use 25, 50, 100, 200, 400, 800')
        
        self.init()
    
    def init(self):
        """Initialize sensor with configuration"""
        # Register addresses
        ALS_CONF_0 = 0x00
        ALS_WH = 0x01
        ALS_WL = 0x02
        POW_SAV = 0x03
        
        # Configure sensor
        self.i2c.writeto_mem(self.address, ALS_CONF_0, self.confValues)
        self.i2c.writeto_mem(self.address, ALS_WH, bytearray([0x00, 0x00]))  # interrupt high
        self.i2c.writeto_mem(self.address, ALS_WL, bytearray([0x00, 0x00]))  # interrupt low
        self.i2c.writeto_mem(self.address, POW_SAV, bytearray([0x00, 0x00])) # power save mode
        print("VEML7700 initialized: IT={}ms, Gain={}".format(
            100 if self.confValues == bytearray([0x00, 0x10]) else "custom",
            "1/8" if self.gain == 0.4608 else str(self.gain)))
    
    def read_lux(self):
        """Read ambient light in lux"""
        try:
            ALS = 0x04
            lux_data = bytearray(2)
            
            # Wait for measurement (40ms should be enough for IT=100ms)
            time.sleep_ms(40)
            
            # Read ALS register
            self.i2c.readfrom_mem_into(self.address, ALS, lux_data)
            
            # Convert to lux value
            lux_raw = lux_data[0] + lux_data[1] * 256
            lux = lux_raw * self.gain
            
            return lux
        except Exception as e:
            print("VEML7700 read error:", e)
            return None

def init_light_sensor(i2c):
    """Initialize VEML7700 light sensor"""
    if not VEML7700_ENABLED:
        return None
    try:
        # Check if sensor is present
        i2c.writeto(VEML7700_ADDRESS, bytearray([0x00]))
        sensor = VEML7700(i2c, VEML7700_ADDRESS)
        print("VEML7700 light sensor initialized at 0x{:02X}".format(VEML7700_ADDRESS))
        return sensor
    except Exception as e:
        print("VEML7700 init failed:", e)
        return None

def read_light_sensor(light_sensor):
    """Read light level in lux"""
    if light_sensor is None:
        return None
    try:
        return light_sensor.read_lux()
    except Exception as e:
        print("Light sensor read error:", e)
        return None

# --- BME680 Sensor ---
def init_sensor(i2c):
    sensor = bme680.BME680_I2C(i2c=i2c, address=0x76)
    return sensor

def read_sensor(sensor):
    """Thread-safe sensor reading"""
    with sensor_lock:
        try:
            return {
                "temperature": sensor.temperature,
                "pressure": sensor.pressure,
                "humidity": sensor.humidity,
                "gas": sensor.gas
            }
        except Exception as e:
            print("Sensor read error:", e)
            return None

# --- Logging ---
def rotate_logs(max_files):
    """Remove old log files beyond max_files limit"""
    try:
        files = [f for f in os.listdir() if f.endswith(".log")]
        files.sort()
        while len(files) > max_files:
            oldest = files.pop(0)
            os.remove(oldest)
            print("Deleted old log:", oldest)
    except Exception as e:
        print("Rotation error:", e)
    gc.collect()

def log_reading(readings, battery_voltage, light_lux, max_files):
    """Log sensor reading to daily file"""
    filename = "{}.log".format(date_str())
    
    # Build log line with available data
    line_parts = [
        timestamp(),
        "{:.2f}".format(readings["temperature"]),
        "{:.2f}".format(readings["pressure"]),
        "{:.2f}".format(readings["humidity"]),
        "{}".format(readings["gas"])
    ]
    
    if light_lux is not None:
        line_parts.append("{:.2f}".format(light_lux))
    
    if battery_voltage is not None:
        line_parts.append("{:.2f}".format(battery_voltage))
    
    line = ", ".join(line_parts) + "\n"
    
    try:
        # Check if this is a new file
        try:
            os.stat(filename)
            new_file = False
        except OSError:
            new_file = True
        
        # Write to log file
        with open(filename, "a") as f:
            if new_file:
                header_parts = ["Time", "Temp(C)", "Pressure(hPa)", "Humidity(%)", "Gas(Ohm)"]
                if light_lux is not None:
                    header_parts.append("Light(lux)")
                if battery_voltage is not None:
                    header_parts.append("Battery(V)")
                f.write(", ".join(header_parts) + "\n")
            f.write(line)
        
        print("Logged:", line.strip())
        
        # Only rotate when creating a new file
        if new_file:
            rotate_logs(max_files)
            
    except Exception as e:
        print("Log error:", e)
    
    gc.collect()

# --- Web Server ---
def get_log_files():
    """Get list of log files with sizes"""
    try:
        files = []
        for f in os.listdir():
            if f.endswith(".log"):
                try:
                    stat = os.stat(f)
                    size_kb = stat[6] / 1024  # Size in KB
                    files.append((f, size_kb))
                except:
                    files.append((f, 0))
        files.sort(reverse=True)  # Newest first
        return files
    except Exception as e:
        print("Error listing files:", e)
        return []

def serve_log_file(cl, filename):
    """Send a log file for download - streams in chunks to save memory"""
    try:
        # Get file size first
        file_size = os.stat(filename)[6]
        
        # Send headers
        response = "HTTP/1.1 200 OK\r\n"
        response += "Content-Type: text/csv\r\n"
        response += "Content-Disposition: attachment; filename=\"{}\"\r\n".format(filename)
        response += "Content-Length: {}\r\n".format(file_size)
        response += "Connection: close\r\n\r\n"
        cl.send(response)
        
        # Stream file in 512-byte chunks
        with open(filename, 'r') as f:
            while True:
                chunk = f.read(512)
                if not chunk:
                    break
                cl.send(chunk)
                gc.collect()  # Free memory after each chunk
        
        print("Sent file: {} ({} bytes)".format(filename, file_size))
        
    except Exception as e:
        print("Error sending file:", e)
        try:
            error_response = "HTTP/1.1 500 Internal Server Error\r\n\r\nError reading file"
            cl.send(error_response)
        except:
            pass

def delete_log_file(filename):
    """Safely delete a log file"""
    try:
        # Security check
        if not filename.endswith('.log') or '/' in filename or '..' in filename:
            return False, "Invalid filename"
        
        # Don't allow deleting today's log file (optional protection)
        current_log = "{}.log".format(date_str())
        if filename == current_log:
            return False, "Cannot delete current day's log file"
        
        # Check if file exists
        try:
            os.stat(filename)
        except OSError:
            return False, "File not found"
        
        # Delete the file
        os.remove(filename)
        print("Deleted log file:", filename)
        gc.collect()
        return True, "File deleted successfully"
        
    except Exception as e:
        print("Error deleting file:", e)
        return False, str(e)

def get_battery_status(voltage):
    """Get battery status string and color"""
    if voltage is None:
        return "N/A", "#999"
    elif voltage > 4.1:
        return "Charging", "#28a745"
    elif voltage > 3.7:
        return "Good", "#28a745"
    elif voltage > 3.4:
        return "Fair", "#ffc107"
    else:
        return "Low", "#dc3545"

def get_light_status(lux):
    """Get light level description"""
    if lux is None:
        return "N/A", "#999"
    elif lux < 10:
        return "Dark", "#666"
    elif lux < 100:
        return "Dim", "#999"
    elif lux < 1000:
        return "Indoor", "#0066cc"
    elif lux < 10000:
        return "Bright", "#ff9800"
    else:
        return "Very Bright", "#ff5722"

def start_server(sensor, light_sensor, adc, wlan):
    """Web server thread for displaying current readings"""
    addr = socket.getaddrinfo('0.0.0.0', 80)[0][-1]
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    
    try:
        s.bind(addr)
        s.listen(1)
        print("Web server listening on port 80")

        while True:
            try:
                cl, addr = s.accept()
                print("Client connected from", addr)
                
                try:
                    request = cl.recv(1024).decode('utf-8')
                    gc.collect()
                    
                    # Parse the request
                    request_lines = request.split('\r\n')
                    request_line = request_lines[0]
                    method = request_line.split(' ')[0] if len(request_line.split(' ')) > 0 else 'GET'
                    path = request_line.split(' ')[1] if len(request_line.split(' ')) > 1 else '/'
                    
                    print("Request: {} {}".format(method, path))
                    
                    # Handle DELETE requests
                    if method == 'DELETE' and path.startswith('/delete/'):
                        filename = path.replace('/delete/', '')
                        success, message = delete_log_file(filename)
                        
                        if success:
                            response = "HTTP/1.1 200 OK\r\n"
                            response += "Content-Type: application/json\r\n"
                            response += "Connection: close\r\n\r\n"
                            response += '{{"success": true, "message": "{}"}}'.format(message)
                        else:
                            response = "HTTP/1.1 400 Bad Request\r\n"
                            response += "Content-Type: application/json\r\n"
                            response += "Connection: close\r\n\r\n"
                            response += '{{"success": false, "message": "{}"}}'.format(message)
                        
                        cl.send(response)
                        cl.close()
                        gc.collect()
                        continue
                    
                    # Handle file download requests
                    if path.startswith('/download/'):
                        filename = path.replace('/download/', '')
                        if filename.endswith('.log') and not '/' in filename and not '..' in filename:
                            serve_log_file(cl, filename)
                            cl.close()
                            gc.collect()
                            continue
                    
                    # Handle logs page
                    if path == '/logs':
                        log_files = get_log_files()
                        
                        if wlan.isconnected():
                            ip_address = wlan.ifconfig()[0]
                        else:
                            ip_address = "Disconnected"
                        
                        current_log = "{}.log".format(date_str())
                        
                        response = """\
HTTP/1.1 200 OK
Content-Type: text/html; charset=UTF-8
Connection: close

<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>BreadBoard - Log Files</title>
<style>
  body {{ font-family: Arial, sans-serif; font-size: 20px; margin: 20px; background: #f5f5f5; }}
  h2   {{ font-size: 28px; color: #333; }}
  table {{ width: 100%; border-collapse: collapse; background: white; margin: 20px 0; }}
  th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }}
  th {{ background-color: #0066cc; color: white; }}
  tr:hover {{ background-color: #f0f0f0; }}
  a {{ color: #0066cc; text-decoration: none; font-weight: bold; }}
  a:hover {{ text-decoration: underline; }}
  .nav {{ margin: 20px 0; }}
  .nav a {{ background: #0066cc; color: white; padding: 10px 20px; border-radius: 5px; display: inline-block; }}
  .nav a:hover {{ background: #0052a3; }}
  .info {{ background: #e7f3ff; padding: 10px; border-left: 4px solid #0066cc; margin: 20px 0; }}
  .btn-delete {{ background: #dc3545; color: white; padding: 6px 12px; border: none; 
                 border-radius: 4px; cursor: pointer; font-size: 16px; font-weight: bold; }}
  .btn-delete:hover {{ background: #c82333; }}
  .btn-delete:disabled {{ background: #ccc; cursor: not-allowed; }}
  .actions {{ display: flex; gap: 10px; align-items: center; }}
  .current-badge {{ background: #28a745; color: white; padding: 2px 8px; border-radius: 3px; 
                    font-size: 14px; font-weight: bold; }}
</style>
<script>
function deleteFile(filename) {{
  if (!confirm('Are you sure you want to delete ' + filename + '?\\n\\nThis action cannot be undone.')) {{
    return;
  }}
  
  var btn = event.target;
  btn.disabled = true;
  btn.textContent = 'Deleting...';
  
  fetch('/delete/' + filename, {{
    method: 'DELETE'
  }})
  .then(response => response.json())
  .then(data => {{
    if (data.success) {{
      alert('✓ ' + data.message);
      location.reload();
    }} else {{
      alert('✗ Error: ' + data.message);
      btn.disabled = false;
      btn.textContent = '🗑 Delete';
    }}
  }})
  .catch(error => {{
    alert('✗ Network error: ' + error);
    btn.disabled = false;
    btn.textContent = '🗑 Delete';
  }});
}}
</script>
</head>
<body>
<h2>📁 Log Files - BreadBoard</h2>
<div class="info">
<p><strong>Sensor IP:</strong> {ip}</p>
<p><strong>Total Files:</strong> {count}</p>
<p><strong>Current Log:</strong> {current}</p>
</div>
<div class="nav">
<a href="/">← Back to Live Readings</a>
</div>
""".format(ip=ip_address, count=len(log_files), current=current_log)

                        if log_files:
                            response += """
<table>
<tr>
<th>Date</th>
<th>Filename</th>
<th>Size</th>
<th>Actions</th>
</tr>
"""
                            for filename, size_kb in log_files:
                                is_current = (filename == current_log)
                                current_badge = '<span class="current-badge">ACTIVE</span>' if is_current else ''
                                delete_btn = '' if is_current else '<button class="btn-delete" onclick="deleteFile(\'{}\')">🗑 Delete</button>'.format(filename)
                                
                                response += """
<tr>
<td>{date} {badge}</td>
<td>{fname}</td>
<td>{size:.1f} KB</td>
<td>
<div class="actions">
<a href="/download/{fname}">⬇ Download</a>
{delete_btn}
</div>
</td>
</tr>
""".format(date=filename.replace('.log', ''), fname=filename, size=size_kb, 
           badge=current_badge, delete_btn=delete_btn)
                            
                            response += "</table>"
                        else:
                            response += "<p><em>No log files available yet.</em></p>"
                        
                        response += """
<div class="nav">
<a href="/">← Back to Live Readings</a>
</div>
<div style="margin-top: 30px; padding: 15px; background: #fff3cd; border-left: 4px solid #ffc107;">
<p style="margin: 0; font-size: 16px;"><strong>Note:</strong> The current day's log file cannot be deleted (protected).</p>
</div>
</body>
</html>
"""
                        cl.send(response)
                        cl.close()
                        gc.collect()
                        continue

                    # Default: show live readings
                    readings = read_sensor(sensor)
                    battery_voltage = read_battery_voltage(adc)
                    light_lux = read_light_sensor(light_sensor)
                    
                    # Get current IP (may change if reconnected)
                    if wlan.isconnected():
                        ip_address = wlan.ifconfig()[0]
                    else:
                        ip_address = "Disconnected"

                    now = time.localtime(time.time() + UTC_OFFSET)
                    ts = "{:02d}:{:02d}:{:02d} {:02d}/{:02d}/{}".format(
                        now[3], now[4], now[5],
                        now[2], now[1], now[0]
                    )

                    if readings:
                        # Battery status
                        battery_status, battery_color = get_battery_status(battery_voltage)
                        battery_display = ""
                        if battery_voltage is not None:
                            battery_display = """
<p>Battery: <span class="value" style="color: {color};">{voltage:.2f}V ({status})</span></p>
""".format(voltage=battery_voltage, status=battery_status, color=battery_color)
                        
                        # Light status
                        light_status, light_color = get_light_status(light_lux)
                        light_display = ""
                        if light_lux is not None:
                            light_display = """
<p>Light Level: <span class="value" style="color: {color};">{lux:.1f} lux ({status})</span></p>
""".format(lux=light_lux, status=light_status, color=light_color)
                        
                        response = """\
HTTP/1.1 200 OK
Content-Type: text/html; charset=UTF-8
Connection: close

<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta http-equiv="refresh" content="60">
<title>BreadBoard Datalogger</title>
<style>
  body {{ font-family: Arial, sans-serif; font-size: 26px; margin: 20px; background: #f5f5f5; }}
  h2   {{ font-size: 30px; color: #333; }}
  p    {{ margin: 10px 0; }}
  .value {{ font-weight: bold; color: #0066cc; }}
  .nav {{ margin: 20px 0; }}
  .nav a {{ background: #0066cc; color: white; padding: 12px 24px; border-radius: 5px; 
            text-decoration: none; display: inline-block; font-size: 22px; }}
  .nav a:hover {{ background: #0052a3; }}
  .container {{ background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
</style>
</head>
<body>
<div class="container">
<h2>📊 Current BreadBoard Readings</h2>
<p>Sensor IP: <span class="value">{ip}</span></p>
<p>Timestamp: <span class="value">{ts}</span></p>
<hr>
<p>Temperature: <span class="value">{temp:.2f} °C</span></p>
<p>Pressure: <span class="value">{press:.2f} hPa</span></p>
<p>Humidity: <span class="value">{hum:.2f} %</span></p>
<p>Gas Resistance: <span class="value">{gas} Ω</span></p>
{light}
{battery}
<hr>
<p>This page will automatically refresh every 60 seconds</p>
</div>
<div class="nav">
<a href="/logs">📁 View Log Files</a>
</div>
</body>
</html>
""".format(ip=ip_address,
           ts=ts,
           temp=float(readings["temperature"]),
           press=float(readings["pressure"]),
           hum=float(readings["humidity"]),
           gas=readings["gas"],
           light=light_display,
           battery=battery_display)
                    else:
                        response = """\
HTTP/1.1 503 Service Unavailable
Content-Type: text/html; charset=UTF-8
Connection: close

<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta http-equiv="refresh" content="5">
<title>BreadBoard Datalogger</title>
</head>
<body>
<h2>⚠ No sensor data available</h2>
<p><strong>DataLogger: {ip}</strong></p>
<p><em>Timestamp: {ts}</em></p>
<p>Retrying in 5 seconds...</p>
</body>
</html>
""".format(ip=ip_address, ts=ts)

                    cl.send(response)
                    
                except Exception as e:
                    print("Request handling error:", e)
                finally:
                    cl.close()
                    
                gc.collect()
                
            except Exception as e:
                print("Server error:", e)
                gc.collect()
                
    except Exception as e:
        print("Fatal server error:", e)
    finally:
        s.close()
        print("Server socket closed")


# --- Main Program ---

print("\n=== ESP32-C3 BME680 + VEML7700 Datalogger Starting ===\n")

# Connect to WiFi
wlan = connect_wifi(SSID, PASSWORD)
if wlan is None:
    print("ERROR: Cannot start without WiFi connection")
    print("Resetting in 60 seconds...")
    time.sleep(60)
    machine.reset()

# Sync time
sync_time()

# Initialize I2C bus (shared by both sensors)
print("Initializing I2C bus...")
i2c = I2C(0, scl=Pin(21), sda=Pin(20), freq=100000)

# Scan I2C bus
print("Scanning I2C bus...")
devices = i2c.scan()
if devices:
    print("Found I2C devices at:", [hex(addr) for addr in devices])
else:
    print("WARNING: No I2C devices found!")

# Initialize battery monitor
print("Initializing battery monitor...")
adc = init_battery_monitor()
if adc:
    test_voltage = read_battery_voltage(adc)
    if test_voltage:
        print("Battery voltage: {:.2f}V".format(test_voltage))
    else:
        print("Battery monitoring disabled or not available")

# Initialize BME680 sensor
print("Initializing BME680 sensor...")
sensor = init_sensor(i2c)
time.sleep(2)  # Allow sensor to stabilize

# Test BME680
print("Testing BME680...")
test_reading = read_sensor(sensor)
if test_reading:
    print("BME680 OK:", test_reading)
else:
    print("WARNING: BME680 test failed, but continuing...")

# Initialize VEML7700 light sensor
print("Initializing VEML7700 light sensor...")
light_sensor = init_light_sensor(i2c)
if light_sensor:
    test_light = read_light_sensor(light_sensor)
    if test_light is not None:
        print("VEML7700 OK: {:.1f} lux".format(test_light))
    else:
        print("WARNING: VEML7700 read failed")
else:
    print("VEML7700 not available, continuing without light sensor")

# Start web server in background thread
print("Starting web server thread...")
_thread.start_new_thread(start_server, (sensor, light_sensor, adc, wlan))
time.sleep(1)

print("\n=== System ready, starting logging loop ===")
print("=== Web interface: http://{} ===\n".format(wlan.ifconfig()[0]))

# Main logging loop
last_wifi_check = time.time()
WIFI_CHECK_INTERVAL = 300  # Check WiFi every 5 minutes

while True:
    try:
        # Periodic WiFi reconnection check
        if time.time() - last_wifi_check > WIFI_CHECK_INTERVAL:
            check_wifi_reconnect(wlan, SSID, PASSWORD)
            last_wifi_check = time.time()
        
        # Read sensor data
        readings = read_sensor(sensor)
        
        # Read battery voltage
        battery_voltage = read_battery_voltage(adc)
        
        # Read light level
        light_lux = read_light_sensor(light_sensor)
        
        # Log data
        if readings:
            log_reading(readings, battery_voltage, light_lux, MAX_LOG_FILES)
        else:
            print("Skipping log - no sensor data")
        
        gc.collect()
        time.sleep(LOG_INTERVAL)
        
    except KeyboardInterrupt:
        print("\nStopping datalogger...")
        break
    except Exception as e:
        print("Main loop error:", e)
        gc.collect()
        time.sleep(LOG_INTERVAL)