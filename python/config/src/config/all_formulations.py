from typing import Union

from .cfe import CFE
from .lasam import LASAM
from .lstm import LSTM
from .multi import MultiBMI
from .noahowp import NoahOWP
from .pet import PET
from .sac import SAC
from .sft import SFT
from .sloth import SLOTH
from .smp import SMP
from .snow17 import Snow17
from .topmod import Topmod
from .ueb import UEB
from .topoflow import BmiTopoflowGlacier

# NOTE the order of this union is important for validation
# unless the model class is using smart_union!
KnownFormulations = Union[
    Topmod, CFE, PET, NoahOWP, LSTM, SLOTH, MultiBMI, SFT, SMP, LASAM, Snow17, SAC, UEB, BmiTopoflowGlacier
    # Topmod, CFE, PET, NoahOWP, LSTM, SLOTH, SFT, SMP, LASAM, Snow17, SAC, UEB
]

# See notes in multi.py and formulation.py about the recursive
# type of MultiBMI modules and how the forward_refs are handled.
