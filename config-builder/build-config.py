#!/usr/bin/env python3.8
import argparse
from base64 import b32encode
from dataclasses import dataclass, field
from ipaddress import IPv6Address, IPv6Network
from typing import (Any, Callable, Dict, Iterator, Literal,
                    TextIO, Tuple, Type, TypeVar, Union, cast)
import yaml
from dacite import from_dict
from dacite.config import Config as DaciteConfig
from jinja2 import Template

T = TypeVar("T", bound="FixedSizeUInt")
class FixedSizeUInt(int):
    size: int = 0
    def __new__(cls: Type[T], value: int) -> T:
        cls_max: int = cls.max_value()
        if not 0 <= value <= cls_max:
            raise ValueError(
                f"{value} is outside the range " +
                f"[0, {cls_max}]")
        new = cast(Callable[[Type[T], int], T],
            super().__new__)
        return new(cls, value)

    @classmethod
    def max_value(cls) -> int:
        return 2**(cls.size) - 1

class NodeID(FixedSizeUInt):
    size: int = 40

class NetworkID(FixedSizeUInt):
    size: int = 64


# from https://github.com/zerotier/ZeroTierOne/blob/91b16310ea47a6de96edb488a61494f8ed8c139c/node/InetAddress.cpp#L427
def mk6plane(nwid: NetworkID, nodeid: NodeID
) -> Tuple[IPv6Network, IPv6Network, IPv6Address]:
    """
    Given a ZeroTier node and network ID, return
    a tuple where the first element is the subnet for the
    whole 6plane network, the second is the subnet 
    assigned to the given node id and the 6plane address
    for that node
    """
    prefix = (nwid ^ (nwid >> 8*4)) & ((1 << 8*4) - 1)
    net = IPv6Network(((0xfc << 8*15) +
                       (prefix << 8*11) +
                       (nodeid << 8*6), 80))
    return net.supernet(new_prefix=40), net, net[1]

# from https://github.com/zerotier/ZeroTierOne/blob/b6b11dbf8242ff17c58f10f817d754da3f8c00eb/osdep/LinuxEthernetTap.cpp#L143-L159
def ifname(nwid: NetworkID, trial: int = 0) -> str:
    """
    Given a ZeroTier network ID and a trial number, compute
    the linux interface name for the network adapter
    """
    nwid40 = (nwid ^ (nwid >> 8*3) + trial) & \
             ((1 << 8*5) - 1)
    return "zt" + b32encode(nwid40.to_bytes(5, "big")
        ).decode().lower()


def config_suffix_append(
    net: IPv6Network, 
    suffix: Union[str, Tuple[str, int]]
) -> IPv6Network:
    plen: int
    nsuffix: int
    if isinstance(suffix, str):
        nsuffix = int(suffix, 16) << \
            128 - net.prefixlen - len(suffix)*4
        plen = len(suffix)*4 + net.prefixlen
    else:
        nsuffix = int(suffix[0], 16)
        plen = suffix[1]
    return IPv6Network((net[nsuffix], plen))

@dataclass()
class IfaceConfig:
    suffix: str
    static_clients: Dict[IPv6Address, str]
    _parent: "Config" = field(init=False, repr=False)

    @property
    def with_prefix(self) -> IPv6Network:
        return config_suffix_append(
            self._parent.with_prefix,
            self.suffix)

    def format_client(self, suffix: str) -> IPv6Address:
        return self.with_prefix[int(suffix, 16)]

    @property
    def statics(self) -> \
            Iterator[Tuple[IPv6Address, IPv6Address]]:
        return ((ll , self.format_client(addr)) \
            for ll, addr in self.static_clients.items())

@dataclass(frozen=True)
class Config:
    version: Literal[1]
    node_id: NodeID
    network_id: NetworkID
    suffix: Union[str, Tuple[str, int]]
    ifaces: Dict[str, IfaceConfig]

    @property
    def zt_iface(self) -> str:
        return ifname(self.network_id)

    @property
    def zt_6plane_nets(self
    ) -> Tuple[IPv6Network, IPv6Network]:
        net, devnet, _ = mk6plane(self.network_id, 
        self.node_id)
        return net, devnet

    @property
    def with_prefix(self) -> IPv6Network:
        _, devnet = self.zt_6plane_nets
        return config_suffix_append(devnet, 
        self.suffix)

    @classmethod
    def from_dict(cls, dict: Dict[Any, Any]):
        self: cls = from_dict(cls, dict, 
            config=DaciteConfig(type_hooks={
                NodeID: lambda value: NodeID(
                    int(value, 16)),
                NetworkID: lambda value: NetworkID(
                    int(value, 16)),
                IPv6Address: IPv6Address
            })
        )
        for name, config in self.ifaces.items():
            config._parent = self
        return self

def main():
    parser = argparse.ArgumentParser(description=
        "Configures dibbler and radvd to relay " +
        "ZeroTier 6plane addresses and traffic " +
        "to devices on different networks")
    parser.add_argument("config",
        type=argparse.FileType("r"),
        help="Configuration file in YAML format")
    parser.add_argument("radvd_tmpl",
        type=argparse.FileType("r"),
        help="Template file for radvd",
        metavar="radvd-tmpl")
    parser.add_argument("dibbler_tmpl",
        type=argparse.FileType("r"),
        help="Template file for dibbler",
        metavar="dibbler-tmpl")
    parser.add_argument("radvd_out",
        type=argparse.FileType("w"),
        help="Output config file for radvd",
        metavar="radvd-out")
    parser.add_argument("dibbler_out",
        type=argparse.FileType("w"),
        help="Output config file for dibbler",
        metavar="dibbler-out")

    args = parser.parse_args()
    config_file: TextIO = args.config
    radvd_tmpl: TextIO = args.radvd_tmpl
    dibbler_tmpl: TextIO = args.dibbler_tmpl
    radvd_out: TextIO = args.radvd_out
    dibbler_out: TextIO = args.dibbler_out

    config = Config.from_dict(yaml.load(config_file))
    radvd_out.write(Template(
        radvd_tmpl.read()).render(config=config))
    dibbler_out.write(Template(
        dibbler_tmpl.read()).render(config=config))
    
if __name__ == "__main__":
    main()
