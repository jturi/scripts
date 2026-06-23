# Home Assistant Setup Guide

**Latest version:** Home Assistant **2026.6.4** (released June 19, 2026)

---

## Installation Methods

> **Important:** As of Home Assistant 2025.12, only **HA OS** and **HA Container** are officially supported. Core (Python venv) and Supervised installs were deprecated.

### Feature Comparison

| Feature            | HA OS | Container | Core (deprecated) | Supervised (deprecated) |
|--------------------|-------|-----------|-------------------|------------------------|
| Supervisor         | Yes   | No        | No                | Yes                    |
| Add-ons            | Yes   | No        | No                | Yes                    |
| Auto-updates       | Yes   | No        | No                | Yes                    |
| Backups            | Yes   | Manual    | Manual            | Yes                    |
| Companion App      | Yes   | No        | No                | Yes                    |
| OS control         | No    | Full      | Full              | Full                   |
| Official support   | Yes   | Yes       | No                | No                     |

---

## Option 1: Docker Container Install (Recommended for existing servers)

### Prerequisites

```bash
# Debian/Ubuntu - Install Docker
sudo apt update
sudo apt install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
sudo usermod -aG docker $USER
```

### Directory Setup

```bash
sudo mkdir -p /opt/stacks/homeassistant
cd /opt/stacks/homeassistant
```

### Minimal compose.yaml

```yaml
services:
  homeassistant:
    container_name: homeassistant
    image: "ghcr.io/home-assistant/home-assistant:stable"
    volumes:
      - ./config:/config
      - /etc/localtime:/etc/localtime:ro
      - /run/dbus:/run/dbus:ro
    restart: unless-stopped
    privileged: true
    network_mode: host
    environment:
      TZ: Europe/Budapest
```

### Full Stack (with MQTT + Node-RED)

```yaml
services:
  homeassistant:
    container_name: homeassistant
    image: "ghcr.io/home-assistant/home-assistant:stable"
    volumes:
      - ./hass-config:/config
      - /etc/localtime:/etc/localtime:ro
      - /run/dbus:/run/dbus:ro
    restart: unless-stopped
    privileged: true
    network_mode: host

  mosquitto:
    container_name: mosquitto
    image: eclipse-mosquitto
    ports:
      - 1883:1883
      - 9001:9001
    volumes:
      - ./mosquitto/config:/mosquitto/config
      - ./mosquitto/data:/mosquitto/data
      - ./mosquitto/log:/mosquitto/log
    restart: unless-stopped

  nodered:
    container_name: nodered
    image: nodered/node-red
    ports:
      - 1880:1880
    volumes:
      - ./nodered:/data
    depends_on:
      - homeassistant
      - mosquitto
    restart: unless-stopped
```

### Launch and Access

```bash
docker compose up -d
# Access at http://<YOUR-IP>:8123
```

### Updating

```bash
cd /opt/stacks/homeassistant
docker compose pull
docker compose up -d
```

---

## Option 2: Raw Python venv Install (Deprecated, reference only)

> No longer officially supported since 2025.12. Use only for development.

### Prerequisites

```bash
sudo apt update
sudo apt install -y python3 python3-dev python3-venv python3-pip \
  libffi-dev libssl-dev libjpeg-dev zlib1g-dev autoconf build-essential \
  libopenjp2-7 libtiff6 libturbojpeg0-dev tzdata ffmpeg liblapack3 \
  liblapack-dev libatlas-base-dev libxml2-dev libxslt1-dev \
  libudev-dev pkg-config libavformat-dev libavcodec-dev \
  libavdevice-dev libavutil-dev libswscale-dev libswresample-dev \
  libavfilter-dev libgammu-dev
```

### Create User and Environment

```bash
sudo useradd -rm homeassistant -G dialout,gpio,i2c
sudo mkdir /srv/homeassistant
sudo chown homeassistant:homeassistant /srv/homeassistant

sudo -u homeassistant -H -s
cd /srv/homeassistant
python3 -m venv .
source bin/activate
```

### Install and Run

```bash
pip install --upgrade pip wheel
pip install homeassistant
hass
# Access at http://<YOUR-IP>:8123 (first startup takes several minutes)
```

### Systemd Service (auto-start)

Create `/etc/systemd/system/homeassistant.service`:

```ini
[Unit]
Description=Home Assistant
After=network-online.target

[Service]
Type=simple
User=homeassistant
WorkingDirectory=/srv/homeassistant
ExecStart=/srv/homeassistant/bin/hass -c "/home/homeassistant/.homeassistant"
Restart=on-failure
RestartForceExitStatus=100

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable homeassistant
sudo systemctl start homeassistant
```

### Updating

```bash
sudo -u homeassistant -H -s
cd /srv/homeassistant
source bin/activate
pip install --upgrade homeassistant
```

---

## Option 3: Home Assistant OS (Dedicated appliance)

Flash the image to a Raspberry Pi 4/5, x86-64 PC, or VM (Proxmox, VirtualBox, KVM, Unraid).

- Minimum: 2 GB RAM, 32 GB storage
- Download from: https://www.home-assistant.io/installation/
- Flash with Balena Etcher or Raspberry Pi Imager
- Boot, access at http://homeassistant.local:8123

This is the simplest option but dedicates the entire machine to Home Assistant.

---

## Device Compatibility

### Quick Reference

| Device                     | Integration          | Connection          | Auto-Discovery | Cloud Required |
|----------------------------|----------------------|---------------------|----------------|----------------|
| Roborock Vacuum            | `roborock`           | Hybrid (local+cloud)| No             | Yes            |
| Aqara Presence Sensor FP2  | `homekit_controller` | Local (Wi-Fi)       | Yes            | No             |
| Shelly Devices             | `shelly`             | Fully Local         | Yes            | No             |
| Netatmo Air Quality Monitor| `netatmo`            | Cloud (OAuth)       | Yes            | Yes            |
| Philips Hue                | `hue`                | Local (push/poll)   | Yes            | No             |
| Sonos Sound Bar            | `sonos`              | Local (UPnP push)   | Yes            | No             |

---

### Roborock Vacuum

**Integration:** `roborock` (built-in)

**Setup:**
1. Install the Roborock app (not Mi Home), create account, add your vacuum
2. In HA: Settings > Devices & Services > Add Integration > Roborock
3. Enter email, select server region, enter verification code

**Entities:** Vacuum control (start/stop/dock), map display, fan speed, mop mode/intensity, brush/filter life sensors, child lock, DND, volume control, go-to-position

**Notes:**
- Cloud access always required (even "local" commands need initial cloud auth)
- Updates via polling every 30 seconds (no push)
- S-series, QV-series, Qrevo, and Saros fully supported
- Since 2026.3: map vacuum segments to HA areas for room-based cleaning

---

### Aqara Presence Sensor FP2

**Integration:** `homekit_controller` (HomeKit Controller)

**Setup:**
1. Set up the FP2 in the Aqara app, configure presence zones there
2. Remove the device from Apple HomeKit if previously added
3. HA should auto-discover via HomeKit, or add manually via HomeKit Controller integration

**Features:** mmWave radar presence detection, zone positioning, multi-person detection, light sensor, fall detection (ceiling mount)

**Notes:**
- Zone configuration and fall detection must be set up in the Aqara app first
- Requires 2.4 GHz Wi-Fi (not Zigbee despite Aqara's Zigbee ecosystem)
- Can also integrate via Matter if firmware supports it

---

### Shelly Devices

**Integration:** `shelly` (built-in)

**Setup:**
1. Use Shelly Smart Control app to get devices on Wi-Fi
2. HA auto-discovers Shelly devices automatically
3. Or manually add via Settings > Devices & Services > Shelly > enter device IP

**Entities:** Switches, lights, covers (with tilt on Gen3), climate (TRV), power consumption, temperature, button events, firmware updates

**Notes:**
- **Fully local** - no cloud account needed
- Gen1: enable CoIoT in device settings, set peer to HA IP
- Gen2+: works out of the box for mains-powered devices
- Battery devices need manual wake before first setup
- Shelly BLU series: use BTHome integration instead
- Gen1 firmware 1.9+ required, Gen2 firmware 1.0+ required

---

### Netatmo Smart Indoor Air Quality Monitor

**Integration:** `netatmo` (built-in)

**Setup:**
1. Have a Netatmo account with devices registered
2. In HA: Settings > Devices & Services > Add Integration > Netatmo
3. Log in and authorize via OAuth redirect
4. HA must have an external URL configured for webhook support (port 443)

**Entities:** Temperature, humidity, CO2 level, noise level, air pressure

**Notes:**
- Cloud-only (requires Netatmo API)
- Air Quality Monitor uses polling (no instant webhook events)
- Known webhook issues with Nabu Casa cloud link

---

### Philips Hue

**Integration:** `hue` (built-in)

**Setup:**
1. Ensure Hue Bridge is on the same network
2. HA auto-discovers the bridge
3. Press the physical button on the Hue Bridge when prompted

**Entities:** All lights, motion sensors (temperature + light level), remotes/switches (as triggers), Hue scenes imported automatically

**Features:**
- V2 bridges: instant push state updates
- `hue.activate_scene` supports transitions, dynamic mode, speed, brightness
- Room/zone grouped lights available (disabled by default)

**Alternatives:**
- **Hue BLE** (since 2025.12): Bluetooth-enabled Hue bulbs connect directly
- **ZHA / Zigbee2MQTT**: Pair bulbs directly to a Zigbee coordinator (bridge-free)

---

### Sonos Sound Bar

**Integration:** `sonos` (built-in)

**Setup:**
1. Enable UPnP in Sonos app (Account > Privacy and Security)
2. HA auto-discovers Sonos devices
3. For complex networks, specify IPs in `configuration.yaml`:

```yaml
sonos:
  media_player:
    hosts:
      - 192.168.1.50
    advertise_addr: 192.168.1.100
```

**Soundbar-Specific Controls:** Audio delay (lip sync), night sound, speech enhancement, surround enable, TV autoplay, dialog level (Arc Ultra)

**General Controls:** Play/pause, volume, bass/treble/loudness, crossfade, speaker grouping, alarms, sleep timer, TTS announce mode

**Actions:** `sonos.snapshot`, `sonos.restore`, `sonos.play_queue`, `sonos.set_sleep_timer`, `sonos.update_alarm`

**Notes:**
- TCP port 1400 must be reachable from Sonos devices (falls back to 30s polling)
- TV autoplay and surround changes rely on polling (~30s delay)
- Microphone status is read-only

---

## Recommendation

For an existing Linux server: **Docker Container** install gives you full OS control while keeping HA easy to update. You lose the add-on store but can run equivalent services (MQTT, Node-RED, etc.) as companion containers.

For a dedicated device: **Home Assistant OS** is simpler and gives you the full experience including add-ons and automatic updates.

All six of your devices have native integrations. Four of six work fully locally (Shelly, Aqara FP2, Hue, Sonos). Roborock needs cloud for auth, and Netatmo is cloud-only.
