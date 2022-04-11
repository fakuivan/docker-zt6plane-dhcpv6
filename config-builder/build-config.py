#!/usr/bin/env python3.9
import argparse
from dataclasses import dataclass, field
from ipaddress import IPv6Address, IPv6Network
from typing import (Any, Iterator, Literal,
                    TextIO, Type, Tuple, Union, cast, NamedTuple)
import yaml
from dacite.core import from_dict
from dacite.config import Config as DaciteConfig
from dacite.types import is_instance
from jinja2 import Template
from pyzt import node_6plane_subnet, ifname, NodeID, NetworkID
from pyzt.misc import subnet_at


class Prefix(NamedTuple):
    value: int
    bits: int

    @classmethod
    def from_config(cls, input_: Union[str, tuple[int, int]]
    ) -> "Prefix":
        if not isinstance(input_, str):
            if not is_instance(input_, cast(Type[Any], Tuple[int, int])):
                raise TypeError(
                    f"Expected string or integer pair, got {input_!r}")
            value, bits = input_
            return cls(value, bits)
        for char in input_.lower():
            if char not in "0123456789abcdef":
                raise ValueError(
                    f"Invalid charecter {char!r} in prefix {input_!r}")
        return cls(int(input_, 16), len(input_) * 4)


def prefix_msb(
    net: IPv6Network,
    at: Prefix
) -> IPv6Network:
    return subnet_at(net, at.bits, at.value)


@dataclass()
class IfaceConfig:
    prefix: Prefix
    static_clients: dict[IPv6Address, str]
    _parent: "Config" = field(init=False, repr=False)

    @property
    def with_prefix(self) -> IPv6Network:
        return prefix_msb(
            self._parent.with_prefix,
            self.prefix)

    def format_client(self, suffix: str) -> IPv6Address:
        return self.with_prefix[int(suffix, 16)]

    @property
    def statics(self) -> \
            Iterator[tuple[IPv6Address, IPv6Address]]:
        return ((ll , self.format_client(addr)) \
            for ll, addr in self.static_clients.items())


@dataclass(frozen=True)
class Config:
    version: Literal[1]
    node_id: NodeID
    network_id: NetworkID
    prefix: Prefix
    ifaces: dict[str, IfaceConfig]

    @property
    def zt_iface(self) -> str:
        return ifname(self.network_id)

    @property
    def zt_6plane_nets(self
    ) -> tuple[IPv6Network, IPv6Network]:
        return node_6plane_subnet(self.network_id, self.node_id)

    @property
    def with_prefix(self) -> IPv6Network:
        _, devnet = self.zt_6plane_nets
        return prefix_msb(devnet,
            self.prefix)

    @classmethod
    def from_dict(cls, dict_: dict[Any, Any]) -> "Config":
        self = from_dict(cls, dict_,
            config=DaciteConfig(type_hooks={
                NodeID: NodeID,
                NetworkID: NetworkID,
                IPv6Address: IPv6Address,
                Prefix: Prefix.from_config
            })
        )
        for _, config in self.ifaces.items():
            config._parent = self
        return self


def main() -> None:
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

    config = Config.from_dict(yaml.safe_load(config_file))
    radvd_out.write(Template(
        radvd_tmpl.read()).render(config=config))
    dibbler_out.write(Template(
        dibbler_tmpl.read()).render(config=config))

if __name__ == "__main__":
    main()
