from functools import partial
import os
from pathlib import Path
from typing import List, Optional, Dict, Union
import re
from dataclasses import dataclass
from datetime import datetime
from bs4 import BeautifulSoup
from multiprocessing import Pool
import pandas

import pprint
pp = pprint.PrettyPrinter(indent=4)

def find_victorian_files(dir: str, min_year: int, max_year: int) -> List[Path]:
    import glob
    potential_xmls = glob.glob(str(Path(dir) / "*.xml"))
    xml_year_re = re.compile(r'(\d\d\d\d)[\w]+\.xml')

    victorian_files = []

    for xml in potential_xmls:
        xml_path = Path(xml)
        m = xml_year_re.match(xml_path.name)
        if m:
            year = int(m.group(1))
            if year >= min_year and \
                year <= max_year:
                victorian_files.append(xml_path)
    
    return sorted(victorian_files)

def normalize_text(text: str):
    return re.sub(r'\s+', " ", text.strip(), flags=re.MULTILINE)
def normalize_text_titlecase(text: str):
    return normalize_text(text).title()

@dataclass
class Occupation:
    name: str
    working_class: Optional[bool]
    skilled: Optional[bool]

@dataclass
class Person:
    # <persName...
    name: str
    id: str
    gender: Optional[str]
    age: Optional[int]
    occupation: Optional[Union[str, Occupation]]

@dataclass
class Offence:
    # <rs type="offenceDescription"...
    id: str
    category: str
    subcategory: Optional[str]
    description: str
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
    corrected: bool
    defendants: Dict[str, Person]
    victims: Dict[str, Person]
    offences: Dict[str, Offence]
    verdicts: Dict[str, Verdict]
    punishments: Dict[str, Punishment]
    charges: List[Charge]

# Returns None if some element is inconclusive
# e.g. t18520405-345: an indictment for perjury, which didn't have a valid "verdict"
def parse_trial_tag(trial_tag, occupation_dict: Dict[str, Occupation], special_correction=True) -> Optional[TrialData]:
    # Trial date is in it's own tag
    date_tag = trial_tag.find("interp", type="date", recursive=False)
    date = datetime.strptime(date_tag["value"], "%Y%m%d").date()

    # Trial ID is in the top-level tag
    trial_id = trial_tag["id"]

    # Keep a record if we perform any data corrections
    # example: if a charge lists a verdict that doesn't exist, and only one verdict is defined in the trial,
    #  we swap it to that verdict.
    corrected = False

    # Find the people we care about (we ignore witnesses)
    defendant_tags = trial_tag.find_all("persname", type="defendantName")
    victim_tags = trial_tag.find_all("persname", type="victimName")

    # Create mappings of ID -> Person
    persons = {}
    defendants = {}
    victims = {}
    for p in defendant_tags + victim_tags:
        id = p["id"]

        gender_tag = p.find("interp", inst=id, type="gender")
        gender = normalize_text_titlecase(gender_tag["value"]) if gender_tag else None

        age_tag = p.find("interp", inst=id, type="age")
        try:
            age = int(age_tag["value"]) if age_tag else None
        except ValueError:
            print(f"[warn] Trial {trial_id} person {id} has a non-numeric age \"{age_tag['value']}\"")
            age = None

        occupation_tag = p.find("interp", inst=id, type="occupation")
        occupation = normalize_text_titlecase(occupation_tag["value"]) if occupation_tag else None
        if occupation in occupation_dict:
            occupation = occupation_dict[occupation]

        new_person = Person(
            id=id,
            name=normalize_text_titlecase(p.getText()),
            gender=gender,
            age=age,
            occupation=occupation,
        )
        if id in persons and new_person != persons[id]:
            print(f"Persons {id} already exists, added twice with different values")
            return None
        persons[id] = new_person

        if p in defendant_tags:
            defendants[id] = persons[id]
        elif p in victim_tags:
            victims[id] = persons[id]

    # Create a set of Offences that have been committed against some Victims
    offence_tags = trial_tag.find_all("rs", type="offenceDescription")
    # Victim join = space-separated list of (offence IDs), (victim IDs)
    victim_join_tags = trial_tag.find_all("join", result="offenceVictim")
    victim_joins = [vjt["targets"].split() for vjt in victim_join_tags]
    offences: Dict[str, Offence] = {}
    for o in offence_tags:
        id = o["id"]

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

        new_offence = Offence(
            id=id,
            category=category,
            subcategory=subcategory,
            description=normalize_text_titlecase(o.getText()),
            victims=offence_victims
        )
        if id in offences and new_offence != offences[id]:
            print(f"[fail] Offence {id} already exists, added twice with different values")
            return None
        offences[id] = new_offence

    # Correction: In a lot of cases, the data can be slightly malformed.
    # e.g. t18420131-660, which specified two offences "t18420131-660-offence-1" and "t18420131-660-offence-"
    # but tries to link "t18420131-660-offence-2"
    # The "special correction" looks for an ID that doesn't end with an integer, and adds the integer to the end
    # if special_correction:
    #     offences_unnumbered = [id for id in offences.keys() if id.endswith("-")]
    #     if len(offences_unnumbered) == 1:
    #         print(f"Found unnumbered offence {offences_unnumbered[0]}, correcting")
    #         old_id = offences_unnumbered[0]
    #         new_id = old_id + str(len(offences))
    #         assert new_id not in offences
    #         # Move the offence in the dictionary
    #         offences[new_id] = offences[old_id]
    #         # Remove the old_id from the dictionary
    #         del offences[old_id]
    #         # Set the offences ID
    #         offences[new_id].id = new_id


    # Create the set of Verdicts
    verdict_tags = trial_tag.find_all("rs", type="verdictDescription")
    verdicts = {}
    for v in verdict_tags:
        id = v["id"]

        category_tag = v.find("interp", inst=id, type="verdictCategory")
        category = category_tag["value"]

        subcategory_tag = v.find("interp", inst=id, type="verdictSubcategory")
        subcategory = subcategory_tag["value"] if subcategory_tag else None

        new_verdict = Verdict(
            id=id,
            category=category,
            subcategory=subcategory
        )
        if id in verdicts and new_verdict != verdicts[id]:
            print(f"[fail] Verdict {id} already exists, added twice with different values")
            return None
        verdicts[id] = new_verdict
    # if special_correction:
    #     verdicts_unnumbered = [id for id in verdicts.keys() if id.endswith("-")]
    #     if len(verdicts_unnumbered) == 1:
    #         print(f"Found unnumbered offence {verdicts_unnumbered[0]}, correcting")
    #         old_id = verdicts_unnumbered[0]
    #         new_id = old_id + str(len(verdicts))
    #         assert new_id not in verdicts
    #         # Move the offence in the dictionary
    #         verdicts[new_id] = verdicts[old_id]
    #         # Remove the old_id from the dictionary
    #         del verdicts[old_id]
    #         # Set the verdicts ID
    #         verdicts[new_id].id = new_id

    # Create the set of Punishments applied to some Defendants
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
            # TODO - Check if the punish_joins have any other people not designated as "defendant"?
            punish_defendants += [persons[d_id] for d_id in punish_join if d_id in persons]

        new_punishment = Punishment(
            id=id,
            category=category,
            subcategory=subcategory,
            description=description,
            defendants=punish_defendants
        )
        if id in punishments and new_punishment != punishments[id]:
            print(f"[fail] Punishment {id} already exists, added twice with different values")
            return None
        punishments[id] = new_punishment
    # if special_correction:
    #     punishments_unnumbered = [id for id in punishments.keys() if id.endswith("-")]
    #     if len(punishments_unnumbered) == 1:
    #         print(f"Found unnumbered offence {punishments_unnumbered[0]}, correcting")
    #         old_id = punishments_unnumbered[0]
    #         new_id = old_id + str(len(punishments))
    #         assert new_id not in punishments
    #         # Move the offence in the dictionary
    #         punishments[new_id] = punishments[old_id]
    #         # Remove the old_id from the dictionary
    #         del punishments[old_id]
    #         # Set the punishments ID
    #         punishments[new_id].id = new_id

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
            if len(verdicts) == 1:
                charge_verdicts = [next(iter(verdicts.values()))]
                print(f"[warn] Trial {trial_id} had a charge {charge_join} with no valid verdict, correcting...")
                corrected = True
            else:
                print(f"[fail] Trial {trial_id} had a charge {charge_join} with no valid verdict, skipping...")
                continue

        assert len(charge_verdicts) == 1

        charge_defendants = [defendants[p_id] for p_id in charge_join if p_id in defendants]
        if len(charge_defendants) == 0:
            # Some charge was inconclusive
            if len(defendants) == 1:
                charge_defendants = [next(iter(defendants.values()))]
                print(f"[warn] Trial {trial_id} had a charge {charge_join} with no valid defendant, correcting...")
                corrected = True
            else:
                print(f"[fail] Trial {trial_id} had a charge {charge_join} with no valid defendant, skipping...")
                continue

        charge_offences = [offences[o_id] for o_id in charge_join if o_id in offences]
        if len(charge_offences) == 0:
            # Some charge was inconclusive
            if len(offences) == 1:
                charge_offences = [next(iter(offences.values()))]
                print(f"[warn] Trial {trial_id} had a charge {charge_join} with no valid offence, correcting...")
                corrected = True
            else:
                print(f"[fail] Trial {trial_id} had a charge {charge_join} with no valid offence, skipping...")
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
        print(f"[fail] Trial {trial_id} had no valid charges, skipping...")
        return None

    return TrialData(
        date=date,
        id=trial_id,
        corrected=corrected,
        
        defendants=defendants,
        victims=victims,
        offences=offences,
        verdicts=verdicts,
        punishments=punishments,
        charges=charges
    )

def parse_xml(xml_path: Path, occupation_dict: Dict[str, Occupation]) -> List[TrialData]:
    # Get BeautifulSoup for file
    with open(xml_path, 'r') as tei_xml:
        soup = BeautifulSoup(tei_xml, 'lxml')

    # Foreach trial in day, create a TrialData
    trial_tags = [x for x in soup.find_all("div1") if x["type"] == "trialAccount"]
    trial_datas = []
    for trial_tag in trial_tags:
        # Add the set of trial datas
        try:
            trial_datas.append(parse_trial_tag(trial_tag, occupation_dict))
        except (ValueError, KeyError, AssertionError) as ex:
            raise RuntimeError(f"Parse error in XML {xml_path}") from ex
            # print(f"Parse error in XML {xml_path}: {ex}")

    return trial_datas

def process_data_xml_folder_to_trials_per_date(data_xml_folder: str, min_year: int, max_year: int, occupation_dict: Dict[str, Occupation]) -> Dict[datetime.date, List[TrialData]]:
    if not os.path.isdir(data_xml_folder):
        raise RuntimeError(f"Data path {data_xml_folder} is not a directory")

    files = find_victorian_files(data_xml_folder, min_year, max_year)

    # Create the list of trials performed on each date
    with Pool(8) as p:
        trials_list_per_date = p.map(
            partial(parse_xml, occupation_dict=occupation_dict),
            files,
        )

    trials_per_date = {
        next(t.date for t in trials if t is not None): trials
        for trials in trials_list_per_date
    }

    return trials_per_date

def parse_occupation_csv(occupation_csv_file: str) -> Dict[str, Occupation]:
    df = pandas.read_csv(occupation_csv_file)
    occupation_dict = {}
    for (occ_name, working_class, skilled) in zip(df["Occupation"], df["class"], df["skilled"]):
        if occ_name is None:
            continue
        occ_name = str(occ_name)
        # quick validity check - occupation name must contain at least one letter
        if not re.search('[a-zA-Z]', occ_name):
            continue
        occupation_dict[occ_name] = Occupation(
            name=occ_name,
            working_class=(
                str(working_class).lower().strip() == "w"
                if working_class is not None
                else None
            ),
            skilled=(
                True
                if str(skilled).lower().strip() == "y"
                else (
                    False
                    if str(skilled).lower().strip() == "n"
                    else None
                )
            )
        )
    return occupation_dict
