import argparse
import os
from pathlib import Path
from typing import List,Optional,Dict
import re
from dataclasses import dataclass
import dataclasses
from datetime import datetime
from bs4 import BeautifulSoup
from multiprocessing import Pool
from enum import Enum
import json

import pprint
pp = pprint.PrettyPrinter(indent=4)

MIN_VICTORIAN_YEAR=1833
MAX_VICTORIAN_YEAR=1913

def find_victorian_files(dir: str) -> List[Path]:
    import glob
    potential_xmls = glob.glob(str(Path(dir) / "*.xml"))
    xml_year_re = re.compile(r'(\d\d\d\d)[\w]+\.xml')

    victorian_files = []

    for xml in potential_xmls:
        xml_path = Path(xml)
        m = xml_year_re.match(xml_path.name)
        if m:
            year = int(m.group(1))
            if year >= MIN_VICTORIAN_YEAR and \
                year <= MAX_VICTORIAN_YEAR:
                victorian_files.append(xml_path)
    
    return sorted(victorian_files)

def normalize_text(text: str):
    return re.sub(r'\s+', " ", text.strip(), flags=re.MULTILINE)
def normalize_text_titlecase(text: str):
    return normalize_text(text).title()

@dataclass
class Person:
    # <persName...
    name: str
    id: str
    gender: Optional[str]
    age: Optional[int]

@dataclass
class Offence:
    # <rs type="offenceDescription"...
    id: str
    category: str
    subcategory: Optional[str]
    victims: List[Person] # <join result="offenceVictim"...

@dataclass
class Verdict:
    # <rs type="verdictDescription"...
    id: str
    category: str
    subcategory: Optional[str]

@dataclass
class Charge:
    # <join result="criminalCharge"...
    defendant: List[Person]
    offence: List[Offence]
    verdict: Verdict

@dataclass
class Punishment:
    # <rs type="punishmentDescription"...
    id: str
    category: str
    subcategory: Optional[str]
    description: str
    defendants: List[Person] # <join result="defendantPunishment"...

@dataclass
class TrialData:
    date: datetime.date
    id: str
    defendants: Dict[str, Person]
    victims: Dict[str, Person]
    offences: Dict[str, Offence]
    verdicts: Dict[str, Verdict]
    punishments: Dict[str, Punishment]
    charges: List[Charge]

# Returns None if some element is inconclusive
# e.g. t18520405-345: an indictment for perjury, which didn't have a valid "verdict"
def parse_trial_tag(trial_tag) -> Optional[TrialData]:
    # Trial date is in it's own tag
    date_tag = trial_tag.find("interp", type="date", recursive=False)
    date = datetime.strptime(date_tag["value"], "%Y%m%d").date()

    # Trial ID is in the top-level tag
    trial_id = trial_tag["id"]

    # Find the people we care about (we ignore witnesses)
    defendant_tags = trial_tag.find_all("persname", type="defendantName")
    victim_tags = trial_tag.find_all("persname", type="victimName")

    # Create mappings of ID -> Person
    persons = {}
    defendants = {}
    victims = {}
    for p in defendant_tags + victim_tags:
        id = p["id"]
        if id in persons:
            raise KeyError(f"Persons {id} already exists, added twice")

        gender_tag = p.find("interp", inst=id, type="gender")
        gender = normalize_text_titlecase(gender_tag["value"]) if gender_tag else None

        age_tag = p.find("interp", inst=id, type="age")
        try:
            age = int(age_tag["value"]) if age_tag else None
        except ValueError:
            print(f"Trial {trial_id} person {id} has a non-numeric age \"{age_tag['value']}\"")
            age = None

        persons[id] = Person(
            id=id,
            name=normalize_text_titlecase(p.getText()),
            gender=gender,
            age=age
        )

        if p in defendant_tags:
            defendants[id] = persons[id]
        elif p in victim_tags:
            victims[id] = persons[id]

    # Create a set of Offences that have been committed against some Victims
    offence_tags = trial_tag.find_all("rs", type="offenceDescription")
    # Victim join = space-separated list of (offence IDs), (victim IDs)
    victim_join_tags = trial_tag.find_all("join", result="offenceVictim")
    victim_joins = [vjt["targets"].split() for vjt in victim_join_tags]
    offences = {}
    for o in offence_tags:
        id = o["id"]
        if id in offences:
            raise KeyError(f"Offence {id} already exists, added twice")

        category_tag = o.find("interp", inst=id, type="offenceCategory")
        category = category_tag["value"]

        subcategory_tag = o.find("interp", inst=id, type="offenceSubcategory")
        subcategory = subcategory_tag["value"] if subcategory_tag else None

        offence_victims = []
        for victim_join in victim_joins:
            if id not in victim_join:
                # This join is not join-ing this offence
                continue
            # Count every ID-d person in this join as a victim
            # TODO - Check if the victim_joins have any other people not designated as "victim"?
            offence_victims += [victims[v_id] for v_id in victim_join if v_id in victims]

        offences[id] = Offence(
            id=id,
            category=category,
            subcategory=subcategory,
            victims=offence_victims
        )

    # Create the set of Verdicts
    verdict_tags = trial_tag.find_all("rs", type="verdictDescription")
    verdicts = {}
    for v in verdict_tags:
        id = v["id"]
        if id in verdicts:
            raise KeyError(f"Verdict {id} already exists, added twice")

        category_tag = v.find("interp", inst=id, type="verdictCategory")
        category = category_tag["value"]

        subcategory_tag = v.find("interp", inst=id, type="verdictSubcategory")
        subcategory = subcategory_tag["value"] if subcategory_tag else None

        verdicts[id] = Verdict(
            id=id,
            category=category,
            subcategory=subcategory
        )
    
    # Create the set of Punishments applied to some Defendants
    punishment_tags = trial_tag.find_all("rs", type="punishmentDescription")
    # Defendant Punishment join = space-separated list of (defendant IDs), (punishment IDs)
    punish_join_tags = trial_tag.find_all("join", result="defendantPunishment")
    punish_joins = [pjt["targets"].split() for pjt in punish_join_tags]
    punishments = {}
    for p in punishment_tags:
        id = p["id"]
        if id in punishments:
            raise KeyError(f"Punishment {id} already exists, added twice")

        category_tag = p.find("interp", inst=id, type="punishmentCategory")
        category = category_tag["value"]

        subcategory_tag = p.find("interp", inst=id, type="punishmentSubcategory")
        subcategory = subcategory_tag["value"] if subcategory_tag else None

        description = normalize_text_titlecase(p.getText())

        punish_defendants = []
        for punish_join in punish_joins:
            if id not in punish_join:
                # This join is not join-ing this punishment
                continue
            # Count every ID-d person in this join as a defendant
            # TODO - Check if the punish_joins have any other people not designated as "defendant"?
            punish_defendants += [persons[d_id] for d_id in punish_join if d_id in persons]

        punishments[id] = Punishment(
            id=id,
            category=category,
            subcategory=subcategory,
            description=description,
            defendants=punish_defendants
        )

    # Create the set of Charges:
    #   the Verdict of whether some Defendants committed some Offences
    # Defendant-Offence-Verdict join = space-separated list of (defendant IDs), (punishment IDs)
    charge_join_tags = trial_tag.find_all("join", result="criminalCharge")
    charge_joins = [cjt["targets"].split() for cjt in charge_join_tags]
    charges = []
    for charge_join in charge_joins:
        charge_verdicts = [verdicts[v_id] for v_id in charge_join if v_id in verdicts]

        if len(charge_verdicts) == 0:
            # Some charge was inconclusive
            # e.g. t18520405-345: an indictment for perjury, which didn't have a valid "verdict"
            print(f"Trial {trial_id} had a charge {charge_join} with no valid verdict, ignoring...")
            continue

        assert len(charge_verdicts) == 1

        charge_defendants = [defendants[p_id] for p_id in charge_join if p_id in defendants]
        if len(charge_defendants) == 0:
            # Some charge was inconclusive
            print(f"Trial {trial_id} had a charge {charge_join} with no valid defendant, ignoring...")
            continue

        charge_offences = [offences[o_id] for o_id in charge_join if o_id in offences]
        if len(charge_offences) == 0:
            # Some charge was inconclusive
            print(f"Trial {trial_id} had a charge {charge_join} with no valid offence, ignoring...")
            continue

        if (len(charge_verdicts) + len(charge_defendants) + len(charge_offences)) != len(charge_join):
            print(charge_defendants, charge_offences, charge_verdicts, charge_join)
        assert (len(charge_verdicts) + len(charge_defendants) + len(charge_offences)) == len(charge_join)

        charges.append(Charge(
            charge_defendants,
            charge_offences,
            charge_verdicts[0]
        ))

    if len(charges) == 0:
        print(f"Trial {trial_id} had no valid charges, ignoring...")

    return TrialData(
        date=date,
        id=trial_id,
        
        defendants=defendants,
        victims=victims,
        offences=offences,
        verdicts=verdicts,
        punishments=punishments,
        charges=charges
    )

def parse_xml(xml_path: Path) -> List[TrialData]:
    # Get BeautifulSoup for file
    with open(xml_path, 'r') as tei_xml:
        soup = BeautifulSoup(tei_xml, 'lxml')

    # Foreach trial in day, create a TrialData
    trial_tags = [x for x in soup.find_all("div1") if x["type"] == "trialAccount"]
    trial_datas = []
    for trial_tag in trial_tags:
        # Add the set of trial datas
        try:
            trial_datas.append(parse_trial_tag(trial_tag))
        except (ValueError, KeyError, AssertionError) as ex:
            raise RuntimeError(f"Parse error in XML {xml_path}") from ex

    return trial_datas

def main():
    p = argparse.ArgumentParser("process.py", description="Tool for processing Old Bailey data into a spreadsheet")
    p.add_argument("data_xml_folder", type=str)
    # p.add_argument("primary_key", type=str, choices=["defendant","accuser"])
    p.add_argument("defendant_csv", type=str)
    p.add_argument("accuser_csv", type=str)

    args = p.parse_args()

    if not os.path.isdir(args.data_xml_folder):
        raise argparse.ArgumentException(f"Data path {args.data_xml_folder} is not a directory")

    files = find_victorian_files(args.data_xml_folder)

    # trials_first = parse_xml(files[0])
    # pp.pprint(dataclasses.asdict(trials_first[0]))

    # Create the list of trials performed on each date
    with Pool(16) as p:
        trials_per_date = p.map(parse_xml, files)

    # print(trials_per_date[0][0])

if __name__ == '__main__':
    main()