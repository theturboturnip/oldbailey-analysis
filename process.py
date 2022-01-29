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


def parse_xml(xml_path: Path) -> List[TrialData]:
    with open(xml_path, 'r') as tei_xml:
        soup = BeautifulSoup(tei_xml, 'lxml')

    trial_tags = [x for x in soup.find_all("div1") if x["type"] == "trialAccount"]

    trial_datas = []

    for trial_tag in trial_tags:
        date_tag = trial_tag.find("interp", type="date", recursive=False)
        date = datetime.strptime(date_tag["value"], "%Y%m%d").date()

        id = trial_tag["id"]

        defendant_tags = trial_tag.find_all("persname", type="defendantName")
        victim_tags = trial_tag.find_all("persname", type="victimName")

        persons = {}
        defendants = {}
        victims = {}
        for p in defendant_tags + victim_tags:
            id = p["id"]

            gender_tag = p.find("interp", inst=id, type="gender")
            gender = normalize_text_titlecase(gender_tag["value"]) if gender_tag else None

            age_tag = p.find("interp", inst=id, type="age")
            age = int(age_tag["value"]) if age_tag else None

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

        offence_tags = trial_tag.find_all("rs", type="offenceDescription")
        # Victim join = space-separated list of (offence IDs), (victim IDs)
        victim_join_tags = trial_tag.find_all("join", result="offenceVictim")
        victim_joins = [vjt["targets"].split() for vjt in victim_join_tags]
        offences = {}
        for o in offence_tags:
            id = o["id"]

            category_tag = o.find("interp", inst=id, type="offenceCategory")
            category = category_tag["value"]

            subcategory_tag = o.find("interp", inst=id, type="offenceSubcategory")
            subcategory = subcategory_tag["value"] if subcategory_tag else None

            victims = []
            for victim_join in victim_joins:
                if id not in victim_join:
                    # This join is not join-ing this offence
                    continue
                # Count every ID-d person in this join as a victim
                victims += [persons[v_id] for v_id in victim_join if v_id in persons]

            offences[id] = Offence(
                id=id,
                category=category,
                subcategory=subcategory,
                victims=victims
            )

        verdict_tags = trial_tag.find_all("rs", type="verdictDescription")
        verdicts = {}
        for v in verdict_tags:
            id = v["id"]

            category_tag = v.find("interp", inst=id, type="verdictCategory")
            category = category_tag["value"]

            subcategory_tag = v.find("interp", inst=id, type="verdictSubcategory")
            subcategory = subcategory_tag["value"] if subcategory_tag else None

            verdicts[id] = Verdict(
                id=id,
                category=category,
                subcategory=subcategory
            )
        
        punishment_tags = trial_tag.find_all("rs", type="punishmentDescription")
        # Defendant Punishment join = space-separated list of (defendant IDs), (punishment IDs)
        punish_join_tags = trial_tag.find_all("join", result="defendantPunishment")
        punish_joins = [pjt["targets"].split() for pjt in punish_join_tags]
        punishments = {}
        for p in punishment_tags:
            id = p["id"]

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
                punish_defendants += [persons[d_id] for d_id in punish_join if d_id in persons]

            punishments[id] = Punishment(
                id=id,
                category=category,
                subcategory=subcategory,
                description=description,
                defendants=punish_defendants
            )

        # Defendant-Offence-Verdict join = space-separated list of (defendant IDs), (punishment IDs)
        charge_join_tags = trial_tag.find_all("join", result="criminalCharge")
        charge_joins = [cjt["targets"].split() for cjt in charge_join_tags]
        charges = []
        for charge_join in charge_joins:
            charge_verdicts = [verdicts[v_id] for v_id in charge_join if v_id in verdicts]
            assert len(charge_verdicts) == 1

            charge_defendants = [persons[p_id] for p_id in charge_join if p_id in persons]
            charge_offences = [offences[o_id] for o_id in charge_join if o_id in offences]

            assert len(charge_verdicts) + len(charge_defendants) + len(charge_offences) == len(charge_join)

            charges.append(Charge(
                charge_defendants,
                charge_offences,
                charge_verdicts[0]
            ))
        

        # defendant_names = {
        #     d["id"]: d.getText() 
        #     for d in defendant_tags
        # }
        # victim_names = {
        #     v["id"]: v.getText()
        #     for v in victim_tags
        # }


        trial_datas.append(TrialData(
            date=date,
            id=id,
            
            defendants=defendants,
            victims=victims,
            offences=offences,
            verdicts=verdicts,
            punishments=punishments,
            charges=charges
        ))
        break

    return trial_datas

def main():
    p = argparse.ArgumentParser("process.py", description="Tool for processing Old Bailey data into a spreadsheet")
    p.add_argument("data_xml_folder", type=str)
    p.add_argument("primary_key", type=str, choices=["defendant","accuser"])
    p.add_argument("output_csv", type=str)

    args = p.parse_args()

    if not os.path.isdir(args.data_xml_folder):
        raise argparse.ArgumentException(f"Data path {args.data_xml_folder} is not a directory")

    files = find_victorian_files(args.data_xml_folder)

    trials_first = parse_xml(files[0])
    pp.pprint(dataclasses.asdict(trials_first[0]))

    # with Pool(8) as p:
    #     trials_per_date = p.map(parse_xml, files)

    # print(trials_per_date[0][0])

if __name__ == '__main__':
    main()