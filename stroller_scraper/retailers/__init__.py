from .mumzworld import MumzworldScraper
from .firstcry import FirstCryScraper
from .babyshop import BabyshopScraper
from .momstore import MomStoreScraper
from .mamasandpapas import MamasAndPapasScraper
from .ellijunior import EllieJuniorScraper
from .ounass import OunassScraper
from .bloomingdales import BloomingdalesScraper
from .galerieslafayette import GaleriesLafayetteScraper
from .fivelittleducks import FiveLittleDucksScraper
from .mothercare import MothercareScraper
from .jikel import JikelScraper
from .sophiababy import SophiaBabyScraper
from .birdsandbees import BirdsAndBeesScraper
from .juniorcouture import JuniorCoutureScraper
from .lebouquet import LeBouquetScraper
from .babiesandmore import BabiesAndMoreScraper
from .eggsandsoldiers import EggsAndSoldiersScraper
from .babycare import BabyCareScraper
from .babykish import BabyKishScraper
from .nanan import NananScraper
from .babylife import BabyLifeScraper


def get_scraper_registry():
    return {
        "Mumzworld": MumzworldScraper,
        "FirstCry": FirstCryScraper,
        "Babyshop": BabyshopScraper,
        "Mom Store": MomStoreScraper,
        "Mamas & Papas": MamasAndPapasScraper,
        "Ellie Junior": EllieJuniorScraper,
        "Ounass": OunassScraper,
        "Bloomingdales": BloomingdalesScraper,
        "Galeries Lafayette": GaleriesLafayetteScraper,
        "Five Little Ducks": FiveLittleDucksScraper,
        "Mothercare": MothercareScraper,
        "Jikel": JikelScraper,
        "Sophia Baby": SophiaBabyScraper,
        "Birds and Bees": BirdsAndBeesScraper,
        "Junior Couture": JuniorCoutureScraper,
        "Le Bouquet": LeBouquetScraper,
        "Babies and More": BabiesAndMoreScraper,
        "Eggs and Soldiers": EggsAndSoldiersScraper,
        "Baby Care": BabyCareScraper,
        "Baby Kish": BabyKishScraper,
        "Nanan": NananScraper,
        "BabyLife UAE": BabyLifeScraper,
    }
