"""Bounded LAN discovery and port checks using standard Nmap tooling."""
import ipaddress
import json
import re
import subprocess
import threading
import xml.etree.ElementTree as ET

_scan_lock = threading.Lock()
PRIVATE = [ipaddress.ip_network(value) for value in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16')]
DEFAULT_PORTS = '21,22,23,53,80,139,443,445,548,631,1883,3389,5000,5900,8000,8080,8123,8443,9100'
TOOL = {
    'type': 'function', 'name': 'network_scan', 'strict': True,
    'description': 'Zoek apparaten en open TCP-poorten op het rechtstreeks aangesloten lokale wifi- of ethernetnetwerk. Gebruik target leeg voor automatisch het LAN (maximaal een /24). Je mag ook een lokaal IPv4-adres of CIDR opgeven. Dit voert echte Nmap-discovery uit, geen losse pings. Niet gevonden betekent niet zeker afwezig; apparaten kunnen niet reageren of door wifi-isolatie verborgen zijn. Servicenamen zijn indicaties op basis van poorten, geen bewezen apparaatidentiteit.',
    'parameters': {'type': 'object', 'properties': {
        'target': {'type': 'string', 'description': 'Leeg voor automatisch LAN, of lokaal IPv4-adres/CIDR; maximaal 256 adressen.'},
        'ports': {'type': 'string', 'description': 'Leeg voor 19 gangbare TCP-poorten; anders komma-gescheiden nummers of reeksen, maximaal 64 poorten.'},
    }, 'required': ['target', 'ports'], 'additionalProperties': False},
}


def connected_networks():
    def ip_json(*args):
        result = subprocess.run(['/usr/sbin/ip', '-j', '-4', *args], capture_output=True, text=True, timeout=5, check=True)
        return json.loads(result.stdout)
    defaults = [row.get('dev') for row in ip_json('route', 'show', 'default')]
    result = []
    for row in ip_json('address', 'show', 'up'):
        name = row['ifname']
        if name == 'lo' or name.startswith(('ppp', 'tun', 'wg', 'docker', 'veth')):
            continue
        for address in row.get('addr_info', []):
            if address.get('scope') != 'global' or address.get('family') != 'inet':
                continue
            interface = ipaddress.ip_interface(str(address['local']) + '/' + str(address['prefixlen']))
            if any(interface.network.subnet_of(private) for private in PRIVATE):
                result.append((name not in defaults, name, interface))
    return sorted(result, key=lambda item: item[0])


def scan_target(target):
    connected = connected_networks()
    if not connected:
        raise ValueError('Geen rechtstreeks aangesloten particulier IPv4-LAN gevonden.')
    if not target or target.lower() in {'auto', 'local', 'lan'}:
        _, device, interface = connected[0]
        network = interface.network
        if network.num_addresses > 256:
            network = ipaddress.ip_network(str(interface.ip) + '/24', strict=False)
    else:
        network = ipaddress.ip_network(target, strict=False)
        matches = [item for item in connected if network.version == 4 and network.subnet_of(item[2].network)]
        if not matches:
            raise ValueError('Scan alleen toegestaan op een rechtstreeks aangesloten particulier LAN.')
        _, device, interface = matches[0]
    if network.num_addresses > 256:
        raise ValueError('Maximaal 256 adressen per scan; kies een /24 of kleiner subnet.')
    own = [str(item[2].ip) for item in connected]
    return device, network, own


def scan_ports(value):
    value = value.strip() or DEFAULT_PORTS
    if not re.fullmatch(r'[0-9, -]+', value):
        raise ValueError('Poorten moeten nummers of reeksen zijn, bijvoorbeeld 22,80,443 of 8000-8010.')
    ports = set()
    for part in value.split(','):
        bounds = [int(p.strip()) for p in part.strip().split('-')]
        if len(bounds) > 2 or not 1 <= bounds[0] <= bounds[-1] <= 65535 or bounds[-1] - bounds[0] > 63:
            raise ValueError('Ongeldige poort of reeks; maximaal 64 TCP-poorten.')
        ports.update(range(bounds[0], bounds[-1] + 1))
    if len(ports) > 64:
        raise ValueError('Maximaal 64 TCP-poorten per scan.')
    return ','.join(str(port) for port in sorted(ports))


def nmap(*arguments, timeout=45):
    completed = subprocess.run(['/usr/bin/nmap', *arguments, '-oX', '-'], capture_output=True, text=True, timeout=timeout)
    if completed.returncode:
        raise ValueError('Nmap: ' + completed.stderr.strip()[:400])
    return ET.fromstring(completed.stdout)


def scan(target='', ports=''):
    if not _scan_lock.acquire(blocking=False):
        return 'Er loopt al een netwerkscan; wacht tot die klaar is.'
    try:
        device, network, own = scan_target(target.strip())
        selected_ports = scan_ports(ports)
        discovery = nmap('-sn', '-n', '-e', device, '--max-retries', '1', '--host-timeout', '5s', '--max-rate', '100', '--exclude', ','.join(own), str(network), timeout=35)
        hosts = {}
        for host in discovery.findall('host'):
            if host.find('status').get('state') != 'up':
                continue
            addresses = {address.get('addrtype'): address for address in host.findall('address')}
            if 'ipv4' not in addresses:
                continue
            address = addresses['ipv4'].get('addr')
            if ipaddress.ip_address(address) not in network or address in own:
                continue
            mac = addresses.get('mac')
            hosts[address] = {'mac': mac.get('addr', '') if mac is not None else '', 'vendor': mac.get('vendor', '') if mac is not None else '', 'ports': []}
        ordered = sorted(hosts, key=ipaddress.ip_address)
        note = ''
        if ordered:
            try:
                detail = nmap('-sT', '-Pn', '-n', '--open', '--max-retries', '1', '--host-timeout', '12s', '--max-parallelism', '32', '--max-rate', '100', '-p', selected_ports, *ordered[:64])
                for host in detail.findall('host'):
                    address = host.find("address[@addrtype='ipv4']")
                    if address is None or address.get('addr') not in hosts:
                        continue
                    for port in host.findall('ports/port'):
                        if port.find('state').get('state') == 'open':
                            service = port.find('service')
                            hosts[address.get('addr')]['ports'].append(port.get('portid') + '/tcp ' + (service.get('name', '?') if service is not None else '?'))
            except (ValueError, subprocess.TimeoutExpired, ET.ParseError) as error:
                note = '\nPoortscan niet volledig afgerond: ' + str(error)[:300]
        lines = [f'LAN-scan: {network} via {device}', f'Gevonden apparaten: {len(hosts)} (RetroModem zelf overgeslagen).', 'Geteste TCP-poorten: ' + selected_ports]
        if len(ordered) > 64:
            lines.append('Poorten alleen gecontroleerd voor de eerste 64 apparaten; kies een kleiner bereik voor de rest.')
        for address in ordered:
            item = hosts[address]
            lines.append(address + ' ' + item['mac'] + ' ' + item['vendor'] + '\n  Open: ' + (', '.join(item['ports']) or 'geen gevonden of niet binnen de tijd getest'))
        lines.append('Dit is een momentopname; geen reactie bewijst niet dat een apparaat uitstaat. Servicenamen zijn poortindicaties.')
        return '\n'.join(lines) + note
    except (OSError, ValueError, subprocess.SubprocessError, ET.ParseError) as error:
        return 'Netwerkscan mislukt: ' + str(error)[:500]
    finally:
        _scan_lock.release()
