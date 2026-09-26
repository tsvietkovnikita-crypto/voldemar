# /// script
# requires-python = ">=3.11"
# dependencies = ["oci>=2.140"]
# ///
"""Create the free Oracle Cloud server for Voldemar, retrying while Oracle is "Out of capacity".

Free ARM servers (VM.Standard.A1.Flex) are often sold out; capacity frees up now and then, so
this keeps trying every couple of minutes in every availability domain until one launch succeeds,
then prints the server's public IP. It never creates a second server with the same name.

Needs an Oracle API key in ~/.oci/config (see README -> "Out of capacity"), an existing VCN with a
public subnet (the console's Create-instance form makes one), and the SSH public key to install.

    uv run --script deploy/oracle-create-instance.py [--ssh-key PATH] [--ocpus 1] [--memory 4]
"""

from __future__ import annotations

import argparse
import random
import sys
import time
from pathlib import Path

import oci

SHAPE = "VM.Standard.A1.Flex"
LIVE_STATES = {"PROVISIONING", "STARTING", "RUNNING", "STOPPING", "STOPPED"}


def log(message: str) -> None:
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {message}", flush=True)


def find_image(compute: oci.core.ComputeClient, compartment: str) -> oci.core.models.Image:
    images = compute.list_images(
        compartment,
        operating_system="Canonical Ubuntu",
        operating_system_version="24.04",
        shape=SHAPE,
        sort_by="TIMECREATED",
        sort_order="DESC",
    ).data
    if not images:
        sys.exit("No Ubuntu 24.04 ARM image found in this region.")
    return images[0]


def find_public_subnet(network: oci.core.VirtualNetworkClient, compartment: str) -> str:
    for vcn in network.list_vcns(compartment, lifecycle_state="AVAILABLE").data:
        for subnet in network.list_subnets(compartment, vcn_id=vcn.id).data:
            if subnet.lifecycle_state == "AVAILABLE" and not subnet.prohibit_public_ip_on_vnic:
                return subnet.id
    sys.exit(
        "No public subnet found. Open Compute -> Instances -> Create instance in the console once "
        "(even if it then fails with 'Out of capacity'): it creates the network this script needs."
    )


def public_ip(config: dict, compartment: str, instance_id: str) -> str | None:
    compute = oci.core.ComputeClient(config)
    network = oci.core.VirtualNetworkClient(config)
    for attachment in compute.list_vnic_attachments(compartment, instance_id=instance_id).data:
        vnic = network.get_vnic(attachment.vnic_id).data
        if vnic.public_ip:
            return vnic.public_ip
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--name", default="voldemar")
    parser.add_argument("--ocpus", type=float, default=1)
    parser.add_argument("--memory", type=float, default=4, help="GB")
    parser.add_argument("--ssh-key", default="~/.ssh/voldemar_oracle.pub")
    parser.add_argument("--interval", type=int, default=120, help="seconds between attempts")
    args = parser.parse_args()

    config = oci.config.from_file()
    oci.config.validate_config(config)
    compartment = config["tenancy"]
    identity = oci.identity.IdentityClient(config)
    compute = oci.core.ComputeClient(config)
    network = oci.core.VirtualNetworkClient(config)

    for instance in compute.list_instances(compartment, display_name=args.name).data:
        if instance.lifecycle_state in LIVE_STATES:
            ip = public_ip(config, compartment, instance.id)
            log(f"Server {args.name!r} already exists ({instance.lifecycle_state}), IP {ip}.")
            return

    ssh_key = Path(args.ssh_key).expanduser().read_text(encoding="utf-8").strip()
    image = find_image(compute, compartment)
    subnet_id = find_public_subnet(network, compartment)
    domains = [ad.name for ad in identity.list_availability_domains(compartment).data]
    log(f"Image {image.display_name}; {args.ocpus:g} OCPU / {args.memory:g} GB; domains {domains}")

    attempt = 0
    while True:
        attempt += 1
        for domain in domains:
            details = oci.core.models.LaunchInstanceDetails(
                compartment_id=compartment,
                availability_domain=domain,
                display_name=args.name,
                shape=SHAPE,
                shape_config=oci.core.models.LaunchInstanceShapeConfigDetails(
                    ocpus=args.ocpus, memory_in_gbs=args.memory
                ),
                source_details=oci.core.models.InstanceSourceViaImageDetails(
                    image_id=image.id, boot_volume_size_in_gbs=50
                ),
                create_vnic_details=oci.core.models.CreateVnicDetails(
                    subnet_id=subnet_id, assign_public_ip=True
                ),
                metadata={"ssh_authorized_keys": ssh_key},
            )
            try:
                instance = compute.launch_instance(
                    details, retry_strategy=oci.retry.NoneRetryStrategy()
                ).data
            except oci.exceptions.ServiceError as e:
                if e.status == 500 and "capacity" in (e.message or "").lower():
                    log(f"Attempt {attempt}: out of capacity in {domain.split(':')[-1]}")
                    continue
                if e.status == 429:
                    log(f"Attempt {attempt}: Oracle asks to slow down; waiting longer")
                    time.sleep(args.interval * 3)
                    continue
                log(f"Stopping on an unexpected error: {e.status} {e.code}: {e.message}")
                sys.exit(1)

            log(f"Launched on attempt {attempt} in {domain}; waiting for it to boot...")
            oci.wait_until(
                compute,
                compute.get_instance(instance.id),
                "lifecycle_state",
                "RUNNING",
                max_wait_seconds=900,
            )
            ip = public_ip(config, compartment, instance.id)
            log(f"SERVER READY: {args.name} public IP {ip}")
            return
        time.sleep(args.interval + random.randint(0, 30))


if __name__ == "__main__":
    main()
