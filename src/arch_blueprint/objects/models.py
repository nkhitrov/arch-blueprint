from dataclasses import dataclass, field
from typing import List


@dataclass
class BlueprintObject:
    name: str
    title: str | None = None
    dependencies: List["BlueprintObject"] = field(default_factory=list)


@dataclass
class BlueprintPackage:
    name: str
    objects: List[BlueprintObject] = field(default_factory=list)
    packages: List["BlueprintPackage"] = field(default_factory=list)

# A B C
# 0 1