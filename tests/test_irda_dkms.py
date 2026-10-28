import importlib.util
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("irda_dkms", ROOT / "scripts/prepare-irda-dkms.py")
dkms = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dkms)


def fixture():
    # Representative upstream ordering: optional ISA/PCI modules between USB
    # and the SIR modules required by MY018 and MA-620.
    names = ("irda", "ircomm", "ircomm-tty", "irda-usb", "nsc-ircc", "w83977af_ir",
             "smsc-ircc2", "ali-ircc", "via-ircc", "vlsi_ir", "irtty-sir", "sir-dev", "ma600-sir")
    text = 'PACKAGE_NAME="irda"\nPACKAGE_VERSION="test"\nMAKE[0]="make"\n'
    for index, name in enumerate(names):
        text += (f'BUILT_MODULE_NAME[{index}]="{name}"\n'
                 f'BUILT_MODULE_LOCATION[{index}]="drivers"\n'
                 f'DEST_MODULE_LOCATION[{index}]="/kernel/drivers/net/irda"\n')
    return text + 'AUTOINSTALL="yes"\n'


class IrdaDkmsTests(unittest.TestCase):
    def test_pi_kernel_skips_isa_pci_without_losing_sir_or_usb(self):
        output, removed = dkms.filter_modules(fixture(), "CONFIG_USB=y\nCONFIG_TTY=y\n# CONFIG_PCI is not set\n")
        self.assertEqual(set(removed), {"nsc-ircc", "w83977af_ir", "smsc-ircc2", "ali-ircc", "via-ircc", "vlsi_ir"})
        names = re.findall(r'^BUILT_MODULE_NAME\[\d+\]="([^"]+)"$', output, re.M)
        self.assertEqual(names, ["irda", "ircomm", "ircomm-tty", "irda-usb", "irtty-sir", "sir-dev", "ma600-sir"])
        for field in ("BUILT_MODULE_NAME", "BUILT_MODULE_LOCATION", "DEST_MODULE_LOCATION"):
            self.assertEqual(re.findall(rf"^{field}\[(\d+)\]", output, re.M), list(map(str, range(7))))
        self.assertIn('MAKE[0]="make"', output)
        self.assertIn('AUTOINSTALL="yes"', output)
        self.assertIn('PACKAGE_VERSION="test"', output)

    def test_enabled_isa_and_pci_modules_are_retained(self):
        output, removed = dkms.filter_modules(fixture(), "CONFIG_USB=m\nCONFIG_TTY=y\nCONFIG_PCI=y\nCONFIG_ISA_DMA_API=y\n")
        self.assertEqual(removed, [])
        self.assertEqual(output, fixture())

    def test_missing_required_tty_configuration_fails(self):
        with self.assertRaisesRegex(ValueError, "required"):
            dkms.filter_modules(fixture(), "CONFIG_USB=y\n")

    def test_incomplete_inventory_fails(self):
        text = fixture().replace('BUILT_MODULE_LOCATION[4]="drivers"\n', '')
        with self.assertRaisesRegex(ValueError, "Incomplete"):
            dkms.filter_modules(text, "CONFIG_USB=y\nCONFIG_TTY=y\n")

    def test_filter_is_idempotent(self):
        first, _ = dkms.filter_modules(fixture(), "CONFIG_USB=y\nCONFIG_TTY=y\n")
        second, removed = dkms.filter_modules(first, "CONFIG_USB=y\nCONFIG_TTY=y\n")
        self.assertEqual(second, first)
        self.assertEqual(removed, [])
