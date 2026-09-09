"""Unit tests for prober parsers, using REAL command output captured on
Windows 11 (Wi-Fi hotspot + campus networks).
"""

from prober import (
    parse_bssid_scan,
    parse_gateway_from_routes,
    parse_ping_output,
    parse_visible_networks,
    parse_wifi_interfaces,
)

PING_OK = """\
Pinging 1.1.1.1 with 32 bytes of data:
Reply from 1.1.1.1: bytes=32 time=34ms TTL=54
Reply from 1.1.1.1: bytes=32 time=219ms TTL=54
Reply from 1.1.1.1: bytes=32 time<1ms TTL=54
Reply from 1.1.1.1: bytes=32 time=75ms TTL=54

Ping statistics for 1.1.1.1:
    Packets: Sent = 4, Received = 4, Lost = 0 (0% loss),
Approximate round trip times in milli-seconds:
    Minimum = 0ms, Maximum = 219ms, Average = 82ms
"""

PING_LOSS = """\
Pinging 10.12.144.1 with 32 bytes of data:
Request timed out.
Request timed out.
Request timed out.
General failure.

Ping statistics for 10.12.144.1:
    Packets: Sent = 4, Received = 0, Lost = 4 (100% loss),
"""

PING_DF_BLOCKED = """\
Pinging 1.1.1.1 with 1472 bytes of data:
Packet needs to be fragmented but DF set.
Packet needs to be fragmented but DF set.
Packet needs to be fragmented but DF set.
Packet needs to be fragmented but DF set.

Ping statistics for 1.1.1.1:
    Packets: Sent = 4, Received = 0, Lost = 4 (100% loss),
"""

WIFI_INTERFACES = """\
There is 1 interface on the system:

    Name                   : Wi-Fi
    Description            : Realtek 8852BE Wireless LAN WiFi 6 PCI-E NIC
    GUID                   : 5cd36eb8-fc2a-408f-9401-d99f28154997
    Physical address       : 3c:0a:f3:57:ec:eb
    State                  : connected
    SSID                   : Sai
    BSSID                  : 3e:20:ed:75:89:25
    Network type           : Infrastructure
    Radio type             : 802.11n
    Authentication         : WPA3-Personal
    Cipher                 : CCMP
    Connection mode        : Profile
    Channel                : 10
    Band                   : 2.4 GHz
    Channel width          : 20 MHz
    Receive rate (Mbps)    : 72.2
    Transmit rate (Mbps)   : 72.2
    Signal                 : 100%
"""

ROUTE_PRINT = """\
===========================================================================
Interface List
 12...3c 0a f3 57 ec eb ......Realtek 8852BE Wireless LAN WiFi 6 PCI-E NIC
===========================================================================
IPv4 Route Table
===========================================================================
Active Routes:
Network Destination        Netmask          Gateway       Interface  Metric
          0.0.0.0          0.0.0.0    10.201.48.156    10.201.48.103     55
        127.0.0.0        255.0.0.0         On-link         127.0.0.1    331
===========================================================================
Persistent Routes:
  None
"""

VISIBLE_NETWORKS = """\
Interface name : Wi-Fi
There are 3 networks currently visible.

SSID 1 : Sai
    Network type            : Infrastructure
    Authentication          : WPA3-Personal

SSID 2 : Amrita-5G-D413
    Network type            : Infrastructure
    Authentication          : WPA2-Enterprise

SSID 3 : DIRECT-8f-HP Printer
    Network type            : Infrastructure
    Authentication          : WPA2-Personal
"""

BSSID_SCAN = """\
Interface name : Wi-Fi
There are 2 networks currently visible.

SSID 1 : Sai
    Network type            : Infrastructure
    Authentication          : WPA3-Personal
    Encryption             : CCMP
    BSSID 1                : 3e:20:ed:75:89:25
         Signal             : 100%
         Radio type         : 802.11n
         Channel            : 10
         Band               : 2.4 GHz
    BSSID 2                : aa:bb:cc:dd:ee:ff
         Signal             : 42%
         Radio type         : 802.11n
         Channel            : 6
         Band               : 2.4 GHz

SSID 2 : Campus-5G
    Network type            : Infrastructure
    Authentication          : WPA2-Enterprise
    Encryption             : CCMP
    BSSID 1                : 20:0c:86:ec:58:40
         Signal             : 88%
         Radio type         : 802.11ax
         Channel            : 36
         Band               : 5 GHz
"""


class TestPingParsing:
    def test_success(self):
        r = parse_ping_output(PING_OK, "1.1.1.1", 4)
        assert r.sent == 4
        assert r.received == 4
        assert r.loss_pct == 0.0
        assert r.times_ms == [34.0, 219.0, 1.0, 75.0]  # time<1ms counts as 1
        assert r.avg_ms == 82.25
        assert not r.df_blocked

    def test_total_loss(self):
        r = parse_ping_output(PING_LOSS, "10.12.144.1", 4)
        assert r.sent == 4
        assert r.received == 0
        assert r.loss_pct == 100.0
        assert r.times_ms == []
        assert r.avg_ms is None

    def test_df_blocked(self):
        r = parse_ping_output(PING_DF_BLOCKED, "1.1.1.1", 4)
        assert r.df_blocked
        assert r.loss_pct == 100.0

    def test_timeout_fallback(self):
        # no stats line at all: fall back to counting replies
        r = parse_ping_output("Request timed out.\n", "x", 3)
        assert r.sent == 3
        assert r.received == 0


class TestWifiInterfaces:
    def test_full_parse(self):
        info = parse_wifi_interfaces(WIFI_INTERFACES)
        assert info["state"] == "connected"
        assert info["ssid"] == "Sai"
        assert info["bssid"] == "3e:20:ed:75:89:25"
        assert info["band"] == "2.4 GHz"
        assert info["channel"] == 10
        assert info["radio"] == "802.11n"
        assert info["signal"] == 100
        assert info["rx_rate"] == 72.2
        assert info["tx_rate"] == 72.2

    def test_bssid_not_confused_with_ssid(self):
        info = parse_wifi_interfaces(WIFI_INTERFACES)
        # SSID must be "Sai", not polluted by the BSSID line
        assert info["ssid"] != "3e:20:ed:75:89:25"

    def test_empty(self):
        info = parse_wifi_interfaces("")
        assert info["state"] == "unknown"
        assert info["ssid"] is None


class TestGatewayParsing:
    def test_finds_lowest_metric(self):
        text = ROUTE_PRINT + "          0.0.0.0          0.0.0.0      192.168.1.1     192.168.1.5     25\n"
        assert parse_gateway_from_routes(text) == "192.168.1.1"

    def test_single_route(self):
        assert parse_gateway_from_routes(ROUTE_PRINT) == "10.201.48.156"

    def test_no_route(self):
        assert parse_gateway_from_routes("") is None

    def test_divider_line_not_matched(self):
        # regression: \\s crosses newlines and used to capture the ===== divider
        text = ROUTE_PRINT.replace("10.201.48.103     55\n", "10.201.48.103     55\n===========\n")
        assert parse_gateway_from_routes(text) == "10.201.48.156"


class TestVisibleNetworks:
    def test_ssid_list(self):
        nets = parse_visible_networks(VISIBLE_NETWORKS)
        assert nets == ["Sai", "Amrita-5G-D413", "DIRECT-8f-HP Printer"]


class TestBssidScan:
    def test_aps_parsed(self):
        aps = parse_bssid_scan(BSSID_SCAN)
        assert len(aps) == 3
        sai1 = aps[0]
        assert sai1["ssid"] == "Sai"
        assert sai1["bssid"] == "3e:20:ed:75:89:25"
        assert sai1["signal"] == 100
        assert sai1["channel"] == 10
        assert sai1["band"] == "2.4 GHz"
        campus = aps[2]
        assert campus["ssid"] == "Campus-5G"
        assert campus["channel"] == 36
        assert campus["band"] == "5 GHz"

    def test_empty(self):
        assert parse_bssid_scan("") == []
