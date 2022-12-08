# Copyright 2022 Guillaume Belanger
# See LICENSE file for licensing details.

import unittest
from unittest.mock import patch

import ops.testing
from ops.model import ActiveStatus
from ops.testing import Harness

from charm import Oai5GUDMOperatorCharm


class TestCharm(unittest.TestCase):
    @patch(
        "charm.KubernetesServicePatch",
        lambda charm, ports: None,
    )
    def setUp(self):
        ops.testing.SIMULATE_CAN_CONNECT = True
        self.addCleanup(setattr, ops.testing, "SIMULATE_CAN_CONNECT", False)
        self.harness = Harness(Oai5GUDMOperatorCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()

    def _create_nrf_relation_with_valid_data(self):
        self.harness.set_can_connect(container="udm", val=True)
        relation_id = self.harness.add_relation("fiveg-nrf", "nrf")
        self.harness.add_relation_unit(relation_id=relation_id, remote_unit_name="nrf/0")

        nrf_ipv4_address = "1.2.3.4"
        nrf_port = "81"
        nrf_api_version = "v1"
        nrf_fqdn = "nrf.example.com"
        key_values = {
            "nrf_ipv4_address": nrf_ipv4_address,
            "nrf_port": nrf_port,
            "nrf_fqdn": nrf_fqdn,
            "nrf_api_version": nrf_api_version,
        }
        self.harness.update_relation_data(
            relation_id=relation_id, app_or_unit="nrf", key_values=key_values
        )
        return nrf_ipv4_address, nrf_port, nrf_api_version, nrf_fqdn

    @patch("ops.model.Container.push")
    def test_given_nrf_relation_contains_nrf_info_when_nrf_relation_joined_then_config_file_is_pushed(  # noqa: E501
        self, mock_push
    ):
        self.harness.set_can_connect(container="udm", val=True)
        (
            nrf_ipv4_address,
            nrf_port,
            nrf_api_version,
            nrf_fqdn,
        ) = self._create_nrf_relation_with_valid_data()

        mock_push.assert_called_with(
            path="/openair-udm/etc/udm.conf",
            source="## UDM configuration file\n"
            "UDM =\n"
            "{\n"
            "  INSTANCE_ID = 0;\n"
            '  PID_DIRECTORY = "/var/run";\n\n'
            '  UDM_NAME = "oai-udm";\n\n'
            "  INTERFACES:{\n"
            "    # UDM binded interface for SBI interface (e.g., communication with UDR, AUSF)\n"  # noqa: E501, W505
            '    SBI:{\n        INTERFACE_NAME = "eth0";       # YOUR NETWORK CONFIG HERE\n'
            '        IPV4_ADDRESS   = "read";\n'
            "        PORT           = 80;            # YOUR NETWORK CONFIG HERE (default: 80)\n"  # noqa: E501, W505
            "        PPID           = 60;\n"
            '        API_VERSION    = "v1";\n'
            "        HTTP2_PORT     = 9090;     # YOUR NETWORK CONFIG HERE\n"
            "    };\n"
            "  };\n\n"
            "  # SUPPORT FEATURES\n"
            "  SUPPORT_FEATURES: {\n"
            '    # STRING, {"yes", "no"}, \n'
            '    USE_FQDN_DNS = "yes";    # Set to yes if UDM will relying on a DNS to resolve UDR\'s FQDN\n'  # noqa: E501, W505
            '    USE_HTTP2    = "no";       # Set to yes to enable HTTP2 for AUSF server\n'
            "    REGISTER_NRF = \"no\";    # Set to 'yes' if UDM resgisters to an NRF\n"
            "  }  \n"
            "    \n"
            "  UDR:{\n"
            '    IPV4_ADDRESS   = "127.0.0.1";   # YOUR NETWORK CONFIG HERE\n'
            "    PORT           = 80;           # YOUR NETWORK CONFIG HERE (default: 80)\n"
            '    API_VERSION    = "v1";   # YOUR API VERSION FOR UDR CONFIG HERE\n'
            '    FQDN           = "oai-udr-svc"          # YOUR UDR FQDN CONFIG HERE\n'
            "  };\n"
            "  \n"
            "  NRF :\n"
            "  {\n"
            f'    IPV4_ADDRESS = "{ nrf_ipv4_address }";  # YOUR NRF CONFIG HERE\n'
            f"    PORT         = { nrf_port };            # YOUR NRF CONFIG HERE (default: 80)\n"  # noqa: E501, W505
            f'    API_VERSION  = "{ nrf_api_version }";   # YOUR NRF API VERSION HERE\n'
            f'    FQDN         = "{nrf_fqdn}";          # YOUR NRF FQDN HERE\n'
            "  };",
        )

    @patch("ops.model.Container.push")
    def test_given_nrf_and_db_relation_are_set_when_config_changed_then_pebble_plan_is_created(  # noqa: E501
        self, _
    ):
        self._create_nrf_relation_with_valid_data()

        self.harness.update_config({"sbiIfName": "eth0"})

        expected_plan = {
            "services": {
                "udm": {
                    "override": "replace",
                    "summary": "udm",
                    "command": "/openair-udm/bin/oai_udm -c /openair-udm/etc/udm.conf -o",
                    "startup": "enabled",
                }
            },
        }
        self.harness.container_pebble_ready("udm")
        updated_plan = self.harness.get_container_pebble_plan("udm").to_dict()
        self.assertEqual(expected_plan, updated_plan)
        service = self.harness.model.unit.get_container("udm").get_service("udm")
        self.assertTrue(service.is_running())
        self.assertEqual(self.harness.model.unit.status, ActiveStatus())
