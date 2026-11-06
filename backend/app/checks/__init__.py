from . import colorado, ofac, sam, vendor_site

CHECKS = {module.NAME: module for module in (ofac, sam, colorado, vendor_site)}
OFFICIAL = ("ofac", "sam", "colorado")  # run for every vendor; vendor_site only when a website is given
