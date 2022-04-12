import argparse
from dataclasses import dataclass
from typing import DefaultDict, Dict, List, Optional, Tuple
from collections import Counter, defaultdict
import liboldbailey.process

@dataclass
class OffenceStats:
    n_guilty: int
    n_not_guilty: int
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
                n_guilty = 0,
                n_not_guilty = 0,
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
                # Ignore "miscVerdict" and "specialVerdict"
                is_guilty = None
                if charge.verdict.category == "guilty":
                    is_guilty = True
                elif charge.verdict.category == "notGuilty":
                    is_guilty = False
                else:
                    continue

                for offence in charge.offence:
                    offence_key = (offence.category, offence.subcategory)
                    current_data = offence_stats[offence_key]
                    for person in charge.defendant:
                        if is_guilty:
                            current_data.n_guilty += 1
                        else:
                            current_data.n_not_guilty += 1

                        punishments = [p for p in trial.punishments.values() if person in p.defendants]
                        # if multiple punishments, count all of them?
                        for punishment in punishments:
                            current_data.punishments.update(
                                [(punishment.category, punishment.subcategory)]
                            )
    
    # Now finished building offence_stats
    # print them!
    for offence_key in sorted(offence_stats.keys()):
        print(offence_key)
        offence_stat = offence_stats[offence_key]
        print(f"guilty:\t{offence_stat.n_guilty}\tnot guilty:\t{offence_stat.n_not_guilty}")
        print("Punishments")
        for punishment, n in offence_stat.punishments.most_common():
            print(f"\t{n}\t|\t{punishment}")
    # done

if __name__ == '__main__':
    main()