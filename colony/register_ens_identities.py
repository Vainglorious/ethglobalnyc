#!/usr/bin/env python3
"""Register generated Colony ant ENS identities on Sepolia.

Default mode is a dry-run. Add --broadcast to submit transactions.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

from eth_account import Account
from web3 import Web3
from web3.exceptions import ContractLogicError

from colony_harness.env import load_env_file


SEPOLIA_NAME_WRAPPER = "0x0635513f179D50A207757E05759CbD106d7dFcE8"
SEPOLIA_PUBLIC_RESOLVER = "0xE99638b40E4Fff0129D56f03b55b6bbC4BBE49b5"
SEPOLIA_REGISTRY = "0x00000000000C2E074eC69A0dFb2997BA6C7d2e1e"
SEPOLIA_PUBLIC_RPC = "https://ethereum-sepolia-rpc.publicnode.com"
SEPOLIA_V2_REGISTRY = "0xDEDB92913A25abE1f7BCDD85D8A344a43B398B67"
SEPOLIA_V2_FACTORY = "0xd2A632D8A8b67C2c4398c255CBd7Af8Dd7236198"
SEPOLIA_V2_RESOLVER_IMPLEMENTATION = "0xdcE5205A553573FFd47629327DDdf36186022FfA"
SEPOLIA_V2_RESOLVER_PROXY_LOGIC = "0x917C561a74Df398646e06f3FFAA51DB8e8330C5A"
SEPOLIA_V2_SUBREGISTRY_IMPLEMENTATION = "0x0F99e7Ea74903AfCB7224d0354fD7428A6f92917"
MAX_UINT64 = 2**64 - 1
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
V2_STATUS_REGISTERED = 2
ROLE_UNREGISTER = 1 << 12
ROLE_RENEW = 1 << 16
ROLE_SET_SUBREGISTRY = 1 << 20
ROLE_SET_RESOLVER = 1 << 24
ROLE_UNREGISTER_ADMIN = ROLE_UNREGISTER << 128
ROLE_RENEW_ADMIN = ROLE_RENEW << 128
ROLE_SET_SUBREGISTRY_ADMIN = ROLE_SET_SUBREGISTRY << 128
ROLE_SET_RESOLVER_ADMIN = ROLE_SET_RESOLVER << 128
V2_DEFAULT_OWNER_ROLE_BITMAP = (
    ROLE_UNREGISTER
    | ROLE_RENEW
    | ROLE_SET_SUBREGISTRY
    | ROLE_SET_RESOLVER
    | ROLE_UNREGISTER_ADMIN
    | ROLE_RENEW_ADMIN
    | ROLE_SET_SUBREGISTRY_ADMIN
    | ROLE_SET_RESOLVER_ADMIN
)
V2_ALL_ROLES = int("0x" + "1" * 64, 16)

V2_REGISTRY_ABI = [
    {
        "inputs": [{"internalType": "uint256", "name": "anyId", "type": "uint256"}],
        "name": "getState",
        "outputs": [
            {
                "components": [
                    {"internalType": "uint8", "name": "status", "type": "uint8"},
                    {"internalType": "uint64", "name": "expiry", "type": "uint64"},
                    {"internalType": "address", "name": "latestOwner", "type": "address"},
                    {"internalType": "uint256", "name": "tokenId", "type": "uint256"},
                    {"internalType": "uint256", "name": "resource", "type": "uint256"},
                ],
                "internalType": "struct RegistryDatastore.State",
                "name": "",
                "type": "tuple",
            }
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "uint256", "name": "tokenId", "type": "uint256"}],
        "name": "ownerOf",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "string", "name": "label", "type": "string"}],
        "name": "getSubregistry",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [
            {"internalType": "string", "name": "label", "type": "string"},
            {"internalType": "address", "name": "owner", "type": "address"},
            {"internalType": "address", "name": "registry", "type": "address"},
            {"internalType": "address", "name": "resolver", "type": "address"},
            {"internalType": "uint256", "name": "roleBitmap", "type": "uint256"},
            {"internalType": "uint64", "name": "expires", "type": "uint64"},
        ],
        "name": "register",
        "outputs": [{"internalType": "uint256", "name": "tokenId", "type": "uint256"}],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [
            {"internalType": "uint256", "name": "tokenId", "type": "uint256"},
            {"internalType": "address", "name": "registry", "type": "address"},
        ],
        "name": "setSubregistry",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
]

V2_FACTORY_ABI = [
    {
        "inputs": [
            {"internalType": "address", "name": "implementation", "type": "address"},
            {"internalType": "uint256", "name": "salt", "type": "uint256"},
            {"internalType": "bytes", "name": "data", "type": "bytes"},
        ],
        "name": "deployProxy",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "nonpayable",
        "type": "function",
    }
]

INITIALIZABLE_ABI = [
    {
        "inputs": [
            {"internalType": "address", "name": "admin", "type": "address"},
            {"internalType": "uint256", "name": "roleBitmap", "type": "uint256"},
        ],
        "name": "initialize",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    }
]

ENS_REGISTRY_ABI = [
    {
        "inputs": [{"internalType": "bytes32", "name": "node", "type": "bytes32"}],
        "name": "owner",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "bytes32", "name": "node", "type": "bytes32"}],
        "name": "resolver",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [
            {"internalType": "address", "name": "owner", "type": "address"},
            {"internalType": "address", "name": "operator", "type": "address"},
        ],
        "name": "isApprovedForAll",
        "outputs": [{"internalType": "bool", "name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [
            {"internalType": "bytes32", "name": "node", "type": "bytes32"},
            {"internalType": "address", "name": "resolver", "type": "address"},
        ],
        "name": "setResolver",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [
            {"internalType": "bytes32", "name": "node", "type": "bytes32"},
            {"internalType": "bytes32", "name": "label", "type": "bytes32"},
            {"internalType": "address", "name": "owner", "type": "address"},
            {"internalType": "address", "name": "resolver", "type": "address"},
            {"internalType": "uint64", "name": "ttl", "type": "uint64"},
        ],
        "name": "setSubnodeRecord",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
]

NAME_WRAPPER_ABI = [
    {
        "inputs": [{"internalType": "uint256", "name": "id", "type": "uint256"}],
        "name": "getData",
        "outputs": [
            {"internalType": "address", "name": "owner", "type": "address"},
            {"internalType": "uint32", "name": "fuses", "type": "uint32"},
            {"internalType": "uint64", "name": "expiry", "type": "uint64"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [
            {"internalType": "address", "name": "account", "type": "address"},
            {"internalType": "address", "name": "operator", "type": "address"},
        ],
        "name": "isApprovedForAll",
        "outputs": [{"internalType": "bool", "name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [
            {"internalType": "bytes32", "name": "parentNode", "type": "bytes32"},
            {"internalType": "string", "name": "label", "type": "string"},
            {"internalType": "address", "name": "owner", "type": "address"},
            {"internalType": "address", "name": "resolver", "type": "address"},
            {"internalType": "uint64", "name": "ttl", "type": "uint64"},
            {"internalType": "uint32", "name": "fuses", "type": "uint32"},
            {"internalType": "uint64", "name": "expiry", "type": "uint64"},
        ],
        "name": "setSubnodeRecord",
        "outputs": [{"internalType": "bytes32", "name": "node", "type": "bytes32"}],
        "stateMutability": "nonpayable",
        "type": "function",
    },
]

PUBLIC_RESOLVER_ABI = [
    {
        "inputs": [{"internalType": "bytes[]", "name": "data", "type": "bytes[]"}],
        "name": "multicall",
        "outputs": [{"internalType": "bytes[]", "name": "results", "type": "bytes[]"}],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [
            {"internalType": "bytes32", "name": "node", "type": "bytes32"},
            {"internalType": "address", "name": "a", "type": "address"},
        ],
        "name": "setAddr",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [
            {"internalType": "bytes32", "name": "node", "type": "bytes32"},
            {"internalType": "string", "name": "key", "type": "string"},
            {"internalType": "string", "name": "value", "type": "string"},
        ],
        "name": "setText",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
]


def main() -> None:
    args = parse_args()
    load_env_file(args.env)
    payload = json.loads(Path(args.identity_json).read_text(encoding="utf-8"))
    records = list(payload.get("records") or [])
    if args.agent_id:
        wanted_agent_ids = set(args.agent_id)
        records = [record for record in records if str(record.get("agent_id")) in wanted_agent_ids]
    if args.limit is not None:
        records = records[: args.limit]
    if not records:
        raise SystemExit("No ENS identity records found.")
    parent = str(args.ens_parent or payload.get("ens_parent") or "").strip().lower().strip(".")
    if not parent:
        raise SystemExit("Missing ens_parent in identity JSON. Pass --ens-parent.")
    if args.check_parent:
        w3 = _connect_public(args)
        registry = w3.eth.contract(address=Web3.to_checksum_address(args.registry), abi=ENS_REGISTRY_ABI)
        wrapper = w3.eth.contract(address=Web3.to_checksum_address(args.name_wrapper), abi=NAME_WRAPPER_ABI)
        v2_registry = w3.eth.contract(address=Web3.to_checksum_address(args.v2_registry), abi=V2_REGISTRY_ABI)
        _print_parent_status(registry, wrapper, v2_registry, parent, args.ens_version)
        return

    if args.broadcast:
        w3, account = _connect(args)
        owner = Web3.to_checksum_address(args.owner or account.address)
        registry = w3.eth.contract(address=Web3.to_checksum_address(args.registry), abi=ENS_REGISTRY_ABI)
        wrapper = w3.eth.contract(address=Web3.to_checksum_address(args.name_wrapper), abi=NAME_WRAPPER_ABI)
        resolver = w3.eth.contract(address=Web3.to_checksum_address(args.resolver), abi=PUBLIC_RESOLVER_ABI)
        v2_registry = w3.eth.contract(address=Web3.to_checksum_address(args.v2_registry), abi=V2_REGISTRY_ABI)
        parent_status = _resolve_parent_status_auto(registry, wrapper, v2_registry, parent, args.ens_version)
        if parent_status["version"] == "v2":
            _assert_v2_parent_authority(parent_status, account.address)
            v2_factory = w3.eth.contract(address=Web3.to_checksum_address(args.v2_factory), abi=V2_FACTORY_ABI)
            v2_resolver_address = _ensure_v2_resolver(w3, account, v2_factory, args)
            v2_parent_registry = _ensure_v2_subregistry(w3, account, v2_registry, v2_factory, parent_status, args)
            expiry = args.expiry if args.expiry is not None else _v2_default_expiry(w3, args.v2_duration)
        else:
            _assert_parent_authority(registry, wrapper, parent_status, account.address)
            v2_parent_registry = v2_resolver_address = None
            expiry = args.expiry if args.expiry is not None else (parent_status["expiry"] or MAX_UINT64)
        print(f"Broadcast signer: {account.address}")
        print(f"Subname owner:    {owner}")
        print(f"Parent owner:     {parent_status['controller']}")
        print(f"Parent mode:      {parent_status['mode']}")
        print(f"Parent fuses:     {parent_status['fuses']}")
        print(f"Expiry:           {expiry}")
    else:
        w3 = account = registry = wrapper = resolver = owner = parent_status = expiry = None
        v2_parent_registry = v2_resolver_address = None

    parent_node = namehash(parent)
    print(f"Parent: {parent}")
    print(f"Records: {len(records)}")

    for index, record in enumerate(records, start=1):
        ens_name = str(record["ens_name"])
        label = str(record["label"])
        addr = Web3.to_checksum_address(record["addr"]) if record.get("addr") else None
        text_records = {
            str(key): str(value)
            for key, value in dict(record.get("text") or {}).items()
            if str(value)
        }
        node = namehash(ens_name)
        print(f"\n[{index}/{len(records)}] {ens_name}")
        print(f"  addr: {addr or '(none)'}")
        print(f"  text: {len(text_records)} records")
        if not args.broadcast:
            continue

        if parent_status["version"] == "v2":
            sub_status = v2_parent_registry.functions.getState(label_id(label)).call()
            create_call = None
            if int(sub_status[0]) == V2_STATUS_REGISTERED:
                print(f"  exists: {ens_name}")
            else:
                create_call = v2_parent_registry.functions.register(
                    label,
                    owner,
                    Web3.to_checksum_address(ZERO_ADDRESS),
                    v2_resolver_address,
                    args.v2_role_bitmap,
                    expiry,
                )
            records_resolver = w3.eth.contract(address=v2_resolver_address, abi=PUBLIC_RESOLVER_ABI)
        elif parent_status["mode"] == "wrapped":
            create_call = wrapper.functions.setSubnodeRecord(
                parent_node, label, owner, resolver.address, 0, args.fuses, expiry
            )
            records_resolver = resolver
        else:
            create_call = registry.functions.setSubnodeRecord(
                parent_node, Web3.keccak(text=label), owner, resolver.address, 0
            )
            records_resolver = resolver
        if create_call is not None:
            _send_contract_tx(w3, account, create_call, f"create {ens_name}")
        resolver_calls = []
        if addr is not None:
            resolver_calls.append(records_resolver.functions.setAddr(node, addr)._encode_transaction_data())
        for key, value in text_records.items():
            resolver_calls.append(records_resolver.functions.setText(node, key, value)._encode_transaction_data())
        if resolver_calls:
            _send_contract_tx(w3, account, records_resolver.functions.multicall(resolver_calls), f"write records {ens_name}")

    if not args.broadcast:
        print("\nDry-run only. Add --broadcast to submit Sepolia transactions.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("identity_json", help="JSON generated by run_demo.py/run_match.py --identity-out.")
    parser.add_argument("--env", default="colony/.env", help="Path to .env containing PROJECT_ENS_PRIVATE_KEY/RPC.")
    parser.add_argument("--rpc-url", default=None, help="Sepolia RPC URL. Defaults to SEPOLIA_RPC_URL or a public fallback.")
    parser.add_argument("--private-key-env", default="PROJECT_ENS_PRIVATE_KEY")
    parser.add_argument("--ens-parent", default=None, help="Override parent ENS name from identity JSON.")
    parser.add_argument("--registry", default=SEPOLIA_REGISTRY)
    parser.add_argument("--name-wrapper", default=SEPOLIA_NAME_WRAPPER)
    parser.add_argument("--resolver", default=SEPOLIA_PUBLIC_RESOLVER)
    parser.add_argument("--ens-version", choices=["auto", "v1", "v2"], default="auto")
    parser.add_argument("--v2-registry", default=SEPOLIA_V2_REGISTRY)
    parser.add_argument("--v2-factory", default=SEPOLIA_V2_FACTORY)
    parser.add_argument("--v2-resolver-implementation", default=SEPOLIA_V2_RESOLVER_IMPLEMENTATION)
    parser.add_argument("--v2-resolver-proxy-logic", default=SEPOLIA_V2_RESOLVER_PROXY_LOGIC)
    parser.add_argument("--v2-subregistry-implementation", default=SEPOLIA_V2_SUBREGISTRY_IMPLEMENTATION)
    parser.add_argument("--v2-duration", type=int, default=31536000)
    parser.add_argument("--v2-role-bitmap", type=int, default=V2_DEFAULT_OWNER_ROLE_BITMAP)
    parser.add_argument("--owner", default=None, help="Subname owner. Defaults to the signing wallet.")
    parser.add_argument("--expiry", type=int, default=None, help="Subname expiry. Defaults to the parent wrapped expiry.")
    parser.add_argument("--fuses", type=int, default=0)
    parser.add_argument("--agent-id", action="append", default=[], help="Only process this agent_id. Can be repeated.")
    parser.add_argument("--limit", type=int, default=None, help="Only process the first N records.")
    parser.add_argument("--check-parent", action="store_true", help="Read parent ENS status and exit without a wallet.")
    parser.add_argument("--broadcast", action="store_true", help="Submit Sepolia transactions.")
    return parser.parse_args()


def _connect(args: argparse.Namespace) -> tuple[Web3, Any]:
    w3 = _connect_public(args)
    private_key = os.environ.get(args.private_key_env)
    if not private_key:
        raise SystemExit(f"Missing {args.private_key_env} in {args.env}.")
    return w3, Account.from_key(private_key)


def _connect_public(args: argparse.Namespace) -> Web3:
    rpc_url = args.rpc_url or os.environ.get("SEPOLIA_RPC_URL") or SEPOLIA_PUBLIC_RPC

    w3 = Web3(Web3.HTTPProvider(rpc_url))
    if not w3.is_connected():
        raise SystemExit("Could not connect to Sepolia RPC.")
    chain_id = w3.eth.chain_id
    if chain_id != 11155111:
        raise SystemExit(f"Expected Sepolia chain_id 11155111, got {chain_id}.")
    return w3


def _resolve_parent_status(registry: Any, wrapper: Any, ens_parent: str) -> dict[str, Any]:
    parent_node = namehash(ens_parent)
    parent_id = int.from_bytes(parent_node, byteorder="big")
    zero = Web3.to_checksum_address("0x0000000000000000000000000000000000000000")
    registry_owner = Web3.to_checksum_address(registry.functions.owner(parent_node).call())
    if registry_owner == zero:
        raise SystemExit(
            f"{ens_parent} is not registered in the classic Sepolia ENS Registry. "
            "Register the parent on https://sepolia.app.ens.domains/ or pass a different --ens-parent."
        )
    resolver_address = Web3.to_checksum_address(registry.functions.resolver(parent_node).call())
    if registry_owner.lower() != str(wrapper.address).lower():
        return {
            "version": "v1",
            "mode": "unwrapped",
            "controller": registry_owner,
            "registry_owner": registry_owner,
            "resolver": resolver_address,
            "fuses": 0,
            "expiry": 0,
        }
    try:
        owner, fuses, expiry = wrapper.functions.getData(parent_id).call()
    except ContractLogicError as exc:
        raise SystemExit(f"Could not read NameWrapper data for {ens_parent}: {exc}") from exc
    return {
        "version": "v1",
        "mode": "wrapped",
        "controller": Web3.to_checksum_address(owner),
        "registry_owner": registry_owner,
        "resolver": resolver_address,
        "fuses": int(fuses),
        "expiry": int(expiry),
    }


def _resolve_parent_status_auto(
    registry: Any,
    wrapper: Any,
    v2_registry: Any,
    ens_parent: str,
    ens_version: str,
) -> dict[str, Any]:
    if ens_version in {"auto", "v2"}:
        v2_status = _resolve_v2_parent_status(v2_registry, ens_parent)
        if v2_status is not None:
            return v2_status
        if ens_version == "v2":
            raise SystemExit(f"{ens_parent} is not registered in the ENSv2 Sepolia registry.")
    if ens_version in {"auto", "v1"}:
        return _resolve_parent_status(registry, wrapper, ens_parent)
    raise SystemExit(f"Unsupported ENS version: {ens_version}")


def _resolve_v2_parent_status(v2_registry: Any, ens_parent: str) -> dict[str, Any] | None:
    labels = ens_parent.split(".")
    if len(labels) != 2 or labels[1] != "eth":
        return None
    label = labels[0]
    any_id = label_id(label)
    status, expiry, latest_owner, token_id, resource = v2_registry.functions.getState(any_id).call()
    if int(status) != V2_STATUS_REGISTERED:
        return None
    owner = Web3.to_checksum_address(v2_registry.functions.ownerOf(int(token_id)).call())
    subregistry = Web3.to_checksum_address(v2_registry.functions.getSubregistry(label).call())
    return {
        "version": "v2",
        "mode": "v2",
        "label": label,
        "controller": owner,
        "latest_owner": Web3.to_checksum_address(latest_owner),
        "token_id": int(token_id),
        "resource": int(resource),
        "subregistry": subregistry,
        "fuses": 0,
        "expiry": int(expiry),
    }


def _print_parent_status(registry: Any, wrapper: Any, v2_registry: Any, ens_parent: str, ens_version: str) -> None:
    if ens_version in {"auto", "v2"}:
        v2_status = _resolve_v2_parent_status(v2_registry, ens_parent)
        if v2_status is not None:
            print(f"Parent:      {ens_parent}")
            print("Version:     v2")
            print("Mode:        v2")
            print(f"Controller:  {v2_status['controller']}")
            print(f"Expiry:      {v2_status['expiry']}")
            print(f"Token ID:    {v2_status['token_id']}")
            print(f"Subregistry: {v2_status['subregistry']}")
            if v2_status["subregistry"].lower() == ZERO_ADDRESS.lower():
                print("Ready:       no - deploy and set an ENSv2 subregistry first")
            else:
                print("Ready:       yes")
            return
        if ens_version == "v2":
            print(f"Parent: {ens_parent}")
            print("Version: v2")
            print("Mode:   not_registered")
            return
    try:
        parent_status = _resolve_parent_status(registry, wrapper, ens_parent)
    except SystemExit as exc:
        print(f"Parent: {ens_parent}")
        print("Version: v1")
        print("Mode:   not_registered")
        print(f"Reason: {exc}")
        return
    print(f"Parent:     {ens_parent}")
    print("Version:    v1")
    print(f"Mode:       {parent_status['mode']}")
    print(f"Controller: {parent_status['controller']}")
    print(f"Resolver:   {parent_status['resolver']}")
    print(f"Fuses:      {parent_status['fuses']}")
    print(f"Expiry:     {parent_status['expiry']}")


def _assert_parent_authority(registry: Any, wrapper: Any, parent_status: dict[str, Any], signer: str) -> None:
    zero = Web3.to_checksum_address("0x0000000000000000000000000000000000000000")
    signer = Web3.to_checksum_address(signer)
    parent_owner = parent_status["controller"]
    if parent_owner == zero:
        raise SystemExit(
            "The parent has no controller in the classic Sepolia ENS contracts. "
            "If it was registered in app.ens.dev ENS v2, this script cannot create its subnames yet."
        )
    if parent_owner == signer:
        return
    if parent_status["mode"] == "wrapped":
        approved = bool(wrapper.functions.isApprovedForAll(parent_owner, signer).call())
        if approved:
            return
    else:
        approved = bool(registry.functions.isApprovedForAll(parent_owner, signer).call())
        if approved:
            return
    if not approved:
        raise SystemExit(
            f"Signer {signer} is not allowed to manage the parent ENS name. "
            f"Current {parent_status['mode']} controller is {parent_owner}."
        )


def _assert_v2_parent_authority(parent_status: dict[str, Any], signer: str) -> None:
    signer = Web3.to_checksum_address(signer)
    if Web3.to_checksum_address(parent_status["controller"]) != signer:
        raise SystemExit(
            f"Signer {signer} is not the ENSv2 owner for {parent_status['label']}.eth. "
            f"Current owner is {parent_status['controller']}."
        )


def _ensure_v2_resolver(w3: Web3, account: Any, factory: Any, args: argparse.Namespace) -> str:
    owner = Web3.to_checksum_address(account.address)
    salt = default_owned_resolver_salt(owner)
    resolver_address = compute_proxy_address(
        w3=w3,
        factory=Web3.to_checksum_address(args.v2_factory),
        proxy_logic=Web3.to_checksum_address(args.v2_resolver_proxy_logic),
        deployer=owner,
        salt=salt,
    )
    if w3.eth.get_code(resolver_address):
        print(f"ENSv2 resolver: {resolver_address} (already deployed)")
        return resolver_address
    initializer = w3.eth.contract(abi=INITIALIZABLE_ABI).functions.initialize(owner, V2_ALL_ROLES)
    initialize_data = initializer._encode_transaction_data()
    deploy_call = factory.functions.deployProxy(
        Web3.to_checksum_address(args.v2_resolver_implementation),
        salt,
        initialize_data,
    )
    _send_contract_tx(w3, account, deploy_call, f"deploy ENSv2 resolver {resolver_address}")
    return resolver_address


def _ensure_v2_subregistry(
    w3: Web3,
    account: Any,
    v2_registry: Any,
    factory: Any,
    parent_status: dict[str, Any],
    args: argparse.Namespace,
) -> Any:
    existing = Web3.to_checksum_address(parent_status["subregistry"])
    if existing.lower() != ZERO_ADDRESS.lower():
        print(f"ENSv2 subregistry: {existing} (already set)")
        return w3.eth.contract(address=existing, abi=V2_REGISTRY_ABI)

    owner = Web3.to_checksum_address(account.address)
    salt = default_user_registry_salt(f"{parent_status['label']}.eth")
    initializer = w3.eth.contract(abi=INITIALIZABLE_ABI).functions.initialize(owner, V2_ALL_ROLES)
    initialize_data = initializer._encode_transaction_data()
    deploy_call = factory.functions.deployProxy(
        Web3.to_checksum_address(args.v2_subregistry_implementation),
        salt,
        initialize_data,
    )
    try:
        subregistry = Web3.to_checksum_address(deploy_call.call({"from": owner}))
    except Exception as exc:
        raise SystemExit(f"Could not simulate ENSv2 subregistry deployment: {exc}") from exc
    if not w3.eth.get_code(subregistry):
        _send_contract_tx(w3, account, deploy_call, f"deploy ENSv2 subregistry {subregistry}")
    else:
        print(f"ENSv2 subregistry deployed: {subregistry}")

    _send_contract_tx(
        w3,
        account,
        v2_registry.functions.setSubregistry(parent_status["token_id"], subregistry),
        f"set ENSv2 subregistry {parent_status['label']}.eth",
    )
    return w3.eth.contract(address=subregistry, abi=V2_REGISTRY_ABI)


def _send_contract_tx(w3: Web3, account: Any, call: Any, label: str) -> str:
    nonce = w3.eth.get_transaction_count(account.address)
    tx = call.build_transaction(
        {
            "from": account.address,
            "nonce": nonce,
            "chainId": 11155111,
            **_fee_params(w3),
        }
    )
    tx["gas"] = int(w3.eth.estimate_gas(tx) * 1.2)
    signed = account.sign_transaction(tx)
    raw_transaction = signed.raw_transaction if hasattr(signed, "raw_transaction") else signed.rawTransaction
    tx_hash = w3.eth.send_raw_transaction(raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    if receipt.status != 1:
        raise SystemExit(f"Transaction failed for {label}: {tx_hash.hex()}")
    print(f"  tx: {label} {tx_hash.hex()}")
    return tx_hash.hex()


def _fee_params(w3: Web3) -> dict[str, int]:
    latest = w3.eth.get_block("latest")
    priority_fee = w3.to_wei(1, "gwei")
    base_fee = int(latest.get("baseFeePerGas") or w3.eth.gas_price)
    return {
        "maxPriorityFeePerGas": priority_fee,
        "maxFeePerGas": base_fee * 2 + priority_fee,
    }


def _v2_default_expiry(w3: Web3, duration: int) -> int:
    latest = w3.eth.get_block("latest")
    return int(latest["timestamp"]) + int(duration)


def label_id(label: str) -> int:
    return int.from_bytes(Web3.keccak(text=label), byteorder="big")


def default_user_registry_salt(name: str) -> int:
    registry_id = Web3.keccak(text="UserRegistry")
    encoded = Web3().codec.encode(["bytes32", "bytes32", "uint256"], [registry_id, namehash(name), 0])
    return int.from_bytes(Web3.keccak(encoded), byteorder="big")


def default_owned_resolver_salt(owner: str) -> int:
    resolver_id = Web3.keccak(text="OwnedResolver")
    encoded = Web3().codec.encode(
        ["bytes32", "address", "uint256"],
        [resolver_id, Web3.to_checksum_address(owner), 0],
    )
    return int.from_bytes(Web3.keccak(encoded), byteorder="big")


def compute_proxy_address(
    *,
    w3: Web3,
    factory: str,
    proxy_logic: str,
    deployer: str,
    salt: int,
) -> str:
    outer_salt = Web3.keccak(w3.codec.encode(["address", "uint256"], [Web3.to_checksum_address(deployer), salt]))
    bytecode = bytes.fromhex("3d604d80600a3d3981f3363d3d373d3d3d363d73")
    bytecode += bytes.fromhex(Web3.to_checksum_address(proxy_logic)[2:])
    bytecode += bytes.fromhex("5af43d82803e903d91602b57fd5bf3")
    bytecode += bytes(outer_salt)
    digest = Web3.keccak(b"\xff" + bytes.fromhex(Web3.to_checksum_address(factory)[2:]) + outer_salt + Web3.keccak(bytecode))
    return Web3.to_checksum_address(digest[-20:])


def namehash(name: str) -> bytes:
    node = b"\x00" * 32
    if not name:
        return node
    for label in reversed(name.lower().strip(".").split(".")):
        label_hash = Web3.keccak(text=label)
        node = Web3.keccak(node + label_hash)
    return node


if __name__ == "__main__":
    main()
