import argparse
from typing import DefaultDict, Optional
from collections import Counter, defaultdict
import liboldbailey.process

def main():
    p = argparse.ArgumentParser("get_occupations.py", description="Tool for processing Old Bailey data into a spreadsheet")
    p.add_argument("data_xml_folder", type=str)
    p.add_argument("--min_year", type=int, default=1833)
    p.add_argument("--max_year", type=int, default=1913)
    p.add_argument("occupation_csv", type=str)

    args = p.parse_args()

    trials_per_date = \
        liboldbailey.process.process_data_xml_folder_to_trials_per_date(
            args.data_xml_folder, 
            args.min_year, args.max_year,
            {}
        )

    total = 0
    skipped = 0
    corrected = 0
    d_occupations_per_year: DefaultDict[int, int] = defaultdict(lambda: 0)
    occupations: Counter[Optional[str]] = Counter()
    for date, trials in trials_per_date:
        # Find the first year in which a defendant gave an occupation
        trial_year = date.year
        if trial_year >= 1906:
            d_occupations_per_year[trial_year] += sum(
                bool(d.occupation)
                for t in trials
                if t is not None
                for d in t.defendants.values()
            )

            occupations.update(
                p.occupation
                for t in trials if t is not None
                for p in t.defendants.values() if p is not None
            )
            occupations.update(
                p.occupation
                for t in trials if t is not None
                for p in t.victims.values() if p is not None
            )

        for trial in trials:
            total += 1
            if trial is None:
                skipped += 1
            elif trial.corrected:
                corrected += 1

    print(f"Final Report:\n\tTotal Trials found: {total}\n\tCorrected (see log): {corrected}\n\tSkipped (see log): {skipped}\n\tSuccess(%): {100 - 100*(skipped/total)}")
    print(d_occupations_per_year)

    if args.occupation_csv:
        with open(args.occupation_csv, "w") as f:
            f.write("Occupation,Occurrences\n")
            for o, n in occupations.most_common():
                if not o or o == "No Occupation":
                    # e.g. o is None, '', etc.
                    continue
                f.write(f"{o},{n}\n")

if __name__ == '__main__':
    main()