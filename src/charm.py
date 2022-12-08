#!/usr/bin/env python3
# Copyright 2022 Guillaume Belanger
# See LICENSE file for licensing details.

"""Charmed Operator for the OpenAirInterface 5G Core UDM component."""


import logging

from charms.oai_5g_nrf.v0.fiveg_nrf import FiveGNRFRequires  # type: ignore[import]
from charms.observability_libs.v1.kubernetes_service_patch import (  # type: ignore[import]
    KubernetesServicePatch,
    ServicePort,
)
from jinja2 import Environment, FileSystemLoader
from ops.charm import CharmBase, ConfigChangedEvent
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, WaitingStatus

logger = logging.getLogger(__name__)

BASE_CONFIG_PATH = "/openair-udm/etc"
CONFIG_FILE_NAME = "udm.conf"


class Oai5GUDMOperatorCharm(CharmBase):
    """Charm the service."""

    def __init__(self, *args):
        """Observes juju events."""
        super().__init__(*args)
        self._container_name = "udm"
        self._container = self.unit.get_container(self._container_name)
        self.service_patcher = KubernetesServicePatch(
            charm=self,
            ports=[
                ServicePort(
                    name="http1",
                    port=int(self._config_sbi_interface_port),
                    protocol="TCP",
                    targetPort=int(self._config_sbi_interface_port),
                ),
                ServicePort(
                    name="http2",
                    port=int(self._config_sbi_interface_http2_port),
                    protocol="TCP",
                    targetPort=int(self._config_sbi_interface_http2_port),
                ),
            ],
        )
        self.nrf_requires = FiveGNRFRequires(self, "fiveg-nrf")
        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(self.on.fiveg_nrf_relation_changed, self._on_config_changed)

    def _on_config_changed(self, event: ConfigChangedEvent) -> None:
        """Triggered on any change in configuration.

        Args:
            event: Config Changed Event

        Returns:
            None
        """
        if not self._container.can_connect():
            self.unit.status = WaitingStatus("Waiting for Pebble in workload container")
            event.defer()
            return
        if not self._nrf_relation_created:
            self.unit.status = BlockedStatus("Waiting for relation to NRF to be created")
            return
        if not self.nrf_requires.nrf_ipv4_address_available:
            self.unit.status = WaitingStatus(
                "Waiting for NRF IPv4 address to be available in relation data"
            )
            return
        self._push_config()
        self._update_pebble_layer()
        self.unit.status = ActiveStatus()

    def _update_pebble_layer(self) -> None:
        """Updates pebble layer with new configuration.

        Returns:
            None
        """
        self._container.add_layer("udm", self._pebble_layer, combine=True)
        self._container.replan()
        self.unit.status = ActiveStatus()

    @property
    def _nrf_relation_created(self) -> bool:
        return self._relation_created("fiveg-nrf")

    def _relation_created(self, relation_name: str) -> bool:
        if not self.model.get_relation(relation_name):
            return False
        return True

    def _push_config(self) -> None:
        jinja2_environment = Environment(loader=FileSystemLoader("src/templates/"))
        template = jinja2_environment.get_template(f"{CONFIG_FILE_NAME}.j2")
        content = template.render(
            instance=self._config_instance,
            pid_directory=self._config_pid_directory,
            udm_name=self._config_udm_name,
            sbi_interface_name=self._config_sbi_interface_name,
            sbi_interface_port=self._config_sbi_interface_port,
            sbi_interface_api_version=self._config_sbi_interface_api_version,
            sbi_interface_http2_port=self._config_sbi_interface_http2_port,
            use_fqdn_dns=self._config_use_fqdn_dns,
            udr_ipv4_address=self._config_udr_ipv4_address,
            udr_port=self._config_udr_port,
            udr_api_version=self._config_udr_api_version,
            udr_fqdn=self._config_udr_fqdn,
            nrf_ipv4_address=self.nrf_requires.nrf_ipv4_address,
            nrf_port=self.nrf_requires.nrf_port,
            nrf_api_version=self.nrf_requires.nrf_api_version,
            nrf_fqdn=self.nrf_requires.nrf_fqdn,
        )

        self._container.push(path=f"{BASE_CONFIG_PATH}/{CONFIG_FILE_NAME}", source=content)
        logger.info(f"Wrote file to container: {CONFIG_FILE_NAME}")

    @property
    def _config_file_is_pushed(self) -> bool:
        """Check if config file is pushed to the container."""
        if not self._container.exists(f"{BASE_CONFIG_PATH}/{CONFIG_FILE_NAME}"):
            logger.info(f"Config file is not written: {CONFIG_FILE_NAME}")
            return False
        logger.info("Config file is pushed")
        return True

    @property
    def _config_instance(self) -> str:
        return "0"

    @property
    def _config_pid_directory(self) -> str:
        return "/var/run"

    @property
    def _config_udm_name(self) -> str:
        return "OAI_UDM"

    @property
    def _config_use_fqdn_dns(self) -> str:
        return "yes"

    @property
    def _config_register_nrf(self) -> str:
        return "no"

    @property
    def _config_use_http2(self) -> str:
        return "no"

    @property
    def _config_sbi_interface_name(self) -> str:
        return self.model.config["sbiIfName"]

    @property
    def _config_sbi_interface_port(self) -> str:
        return "80"

    @property
    def _config_sbi_interface_http2_port(self) -> str:
        return "9090"

    @property
    def _config_sbi_interface_api_version(self) -> str:
        return "v1"

    @property
    def _config_udr_ipv4_address(self) -> str:
        return "127.0.0.1"

    @property
    def _config_udr_port(self) -> str:
        return "80"

    @property
    def _config_udr_api_version(self) -> str:
        return "v1"

    @property
    def _config_udr_fqdn(self) -> str:
        return "oai-udr-svc"

    @property
    def _pebble_layer(self) -> dict:
        """Return a dictionary representing a Pebble layer."""
        return {
            "summary": "udm layer",
            "description": "pebble config layer for udm",
            "services": {
                "udm": {
                    "override": "replace",
                    "summary": "udm",
                    "command": f"/openair-udm/bin/oai_udm -c {BASE_CONFIG_PATH}/{CONFIG_FILE_NAME} -o",  # noqa: E501
                    "startup": "enabled",
                }
            },
        }


if __name__ == "__main__":
    main(Oai5GUDMOperatorCharm)