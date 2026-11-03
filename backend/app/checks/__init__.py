from . import colorado, ofac, sam

CHECKS = {module.NAME: module for module in (ofac, sam, colorado)}
