import ipaddress
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import patch
from web import network_tools as net


class ScanTests(unittest.TestCase):
    def setUp(self):
        self.connected = patch.object(net, 'connected_networks', return_value=[(False, 'wlan0', ipaddress.ip_interface('192.168.0.187/24'))])
        self.connected.start()
        self.addCleanup(self.connected.stop)

    def test_default_selects_lan_and_excludes_modem(self):
        device, network, own = net.scan_target('')
        self.assertEqual((device, str(network), own), ('wlan0', '192.168.0.0/24', ['192.168.0.187']))

    def test_public_offlink_and_large_subnet_rejected(self):
        for target in ['8.8.8.8', '10.1.0.0/24', '192.168.0.0/16', '::1', '--script=vuln']:
            with self.subTest(target=target), patch.object(net, 'nmap') as scan:
                self.assertIn('Netwerkscan mislukt', net.scan(target))
                scan.assert_not_called()

    def test_port_ranges_are_bounded_and_no_options_passed(self):
        self.assertEqual(net.scan_ports('22,80,8000-8002'), '22,80,8000,8001,8002')
        for ports in ['1-65535', '0', '65536', '80,--script', '80,', '90-80']:
            with self.subTest(ports=ports), self.assertRaises(ValueError):
                net.scan_ports(ports)

    def test_discovery_mac_and_open_port_results(self):
        discovery = ET.fromstring('<nmaprun><host><status state="up"/><address addrtype="ipv4" addr="192.168.0.1"/><address addrtype="mac" addr="00:11:22:33:44:55" vendor="Router"/></host></nmaprun>')
        detail = ET.fromstring('<nmaprun><host><status state="up"/><address addrtype="ipv4" addr="192.168.0.1"/><ports><port portid="443"><state state="open"/><service name="https"/></port><port portid="22"><state state="closed"/></port></ports></host></nmaprun>')
        with patch.object(net, 'nmap', side_effect=[discovery, detail]) as scan:
            result = net.scan('', '22,443')
            self.assertIn('192.168.0.1 00:11:22:33:44:55 Router', result)
            self.assertIn('443/tcp https', result)
            self.assertNotIn('22/tcp', result)
            self.assertIn('--exclude', scan.call_args_list[0].args)
            self.assertIn('192.168.0.187', scan.call_args_list[0].args)
            self.assertEqual(scan.call_args_list[1].args[-1], '192.168.0.1')
