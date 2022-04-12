import argparse
from dataclasses import dataclass
from typing import DefaultDict, Dict, List, Optional, Tuple
from collections import Counter, defaultdict
import liboldbailey.process

@dataclass
class OffenceStats:
    verdict_categories: 'Counter[str]'
    verdicts: 'Counter[Tuple[str, Optional[str]]]'
    numerical_values: List[int]
    punishments: 'Counter[Tuple[str, Optional[str]]]'

def main():
    p = argparse.ArgumentParser("get_occupations.py", description="Tool for processing Old Bailey data into a spreadsheet")
    p.add_argument("data_xml_folder", type=str)
    p.add_argument("--min_year", type=int, default=1833)
    p.add_argument("--max_year", type=int, default=1913)
    p.add_argument("--occupation_csv", type=str)

    args = p.parse_args()

    occupation_dict = {}
    if args.occupation_csv:
        occupation_dict = liboldbailey.process.parse_occupation_csv(args.occupation_csv)

    trials_per_date = \
        liboldbailey.process.process_data_xml_folder_to_trials_per_date(
            args.data_xml_folder, 
            args.min_year, args.max_year,
            occupation_dict
        )

    # Gather by offence
    offence_stats: Dict[Tuple[str,Optional[str]], OffenceStats] = \
        defaultdict(
            lambda: OffenceStats(
                verdict_categories = Counter(),
                verdicts = Counter(),
                numerical_values = [],
                punishments = Counter()
            )
        )
    for date, trials in trials_per_date.items():
        for trial in trials:
            if trial is None:
                continue

            # Count stats for each Offence for each Person in each Charge
            # if a Charge has multiple Offences, 
            # the single Verdict for that Charge counts for all Offences
            # if a Charge has multiple People,
            # the single Verdict for that Charge counts for all Offences for each Person
            # punishments have to be counted per Person
            # if the Verdict is guilty, the punishment for each Person in the Charge is counted for each Offence

            for charge in trial.charges:
                for offence in charge.offence:
                    offence_key = (offence.category, offence.subcategory)
                    current_data = offence_stats[offence_key]

                    current_data.verdicts.update([
                        (charge.verdict.category, charge.verdict.subcategory)
                    ])
                    current_data.verdict_categories.update([
                        charge.verdict.category
                    ])

                    # only count punishments for guilty verdicts
                    if charge.verdict.category != "guilty":
                        continue
                    for person in charge.defendant:
                        # if multiple punishments, count all of them?
                        current_data.punishments.update(
                            [
                                (p.category, p.subcategory)
                                for p in trial.punishments.values()
                                if person in p.defendants
                            ]
                        )
    
    # Now finished building offence_stats
    # print them!
    for offence_key in sorted(offence_stats.keys()):
        print(offence_key)
        offence_stat = offence_stats[offence_key]
        print(f"guilty:\t{offence_stat.verdict_categories['guilty']}\tnot guilty:\t{offence_stat.verdict_categories['notGuilty']}")
        print("Verdicts")
        for verdict, n in offence_stat.verdicts.most_common():
            print(f"\t{n}\t|\t{verdict}")
        print("Punishments (guilty verdicts only)")
        for punishment, n in offence_stat.punishments.most_common():
            print(f"\t{n}\t|\t{punishment}")
    # done

if __name__ == '__main__':
    main()