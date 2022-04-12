import argparse
from dataclasses import dataclass
from itertools import groupby
from typing import DefaultDict, Dict, List, Optional, Tuple
from collections import Counter, defaultdict
import liboldbailey.process

import pandas as pd

CategorySubcategory = Tuple[str, Optional[str]]

@dataclass
class OffenceSummary:
    verdict_categories: 'Counter[str]'
    verdicts: 'Counter[CategorySubcategory]'
    numerical_values: List[int]
    punishments: 'Counter[CategorySubcategory]'

def write_summary_sheet(summaries: Dict[CategorySubcategory, OffenceSummary], writer: pd.ExcelWriter, min_year: int, max_year: int, category_on_one_row: bool = True):
    # Based on https://datascience.stackexchange.com/a/46451
    workbook = writer.book
    worksheet = workbook.add_worksheet("Summary")
    writer.sheets["Summary"] = worksheet

    # First, write some generic stats
    worksheet.write_string(0, 0, "Offence Summary")
    worksheet.write_string(1, 0, "Start Year")
    worksheet.write_number(1, 1, min_year)
    worksheet.write_string(2, 0, "End Year")
    worksheet.write_number(2, 1, max_year)

    # Keep track of the first row for the current offences summmary
    current_start_row = 4
    # Put each category on the same set of rows, with a new column for each subcategory
    for category, offence_keys in groupby(sorted(summaries.keys()), lambda k: k[0]):
        current_column = 0
        group_end_rows = []
        for offence_key in offence_keys:
            offence_summary = summaries[offence_key]

            # Write the name of the offence
            worksheet.write_string(current_start_row, current_column + 0, offence_key[0])
            worksheet.write_string(current_start_row, current_column + 1, str(offence_key[1]))

            # Write the guilty/not guilty breakdown
            worksheet.write_string(current_start_row + 1, current_column + 0, "Guilty Verdicts: ")
            worksheet.write_number(current_start_row + 1, current_column + 1, offence_summary.verdict_categories['guilty'])
            worksheet.write_string(current_start_row + 2, current_column + 0, "Not Guilty Verdicts: ")
            worksheet.write_number(current_start_row + 2, current_column + 1, offence_summary.verdict_categories['notGuilty'])

            # Write the full verdict breakdown
            worksheet.write_string(current_start_row + 4, current_column + 0, "Verdict Breakdown: ")
            # Start one row ahead, so we can write the table headers in
            verdict_row = current_start_row + 6
            for verdict, n in offence_summary.verdicts.most_common():
                worksheet.write_string(verdict_row, current_column + 0, verdict[0])
                worksheet.write_string(verdict_row, current_column + 1, str(verdict[1]))
                worksheet.write_number(verdict_row, current_column + 2, n)
                verdict_row += 1
            # Make it a table
            worksheet.add_table(
                current_start_row + 5, current_column + 0,
                verdict_row, current_column + 2,
                {
                    'columns': [{'header': "Category"}, {'header': "Subcategory"}, {'header': "Count"}]
                }
            )

            # Write the full punishment breakdown
            worksheet.write_string(verdict_row + 1, current_column + 0, "Punishment Breakdown: ")
            # Start one row ahead, so we can write the table headers in
            punishment_row = verdict_row + 3
            for punishment, n in offence_summary.punishments.most_common():
                worksheet.write_string(punishment_row, current_column + 0, punishment[0])
                worksheet.write_string(punishment_row, current_column + 1, str(punishment[1]))
                worksheet.write_number(punishment_row, current_column + 2, n)
                punishment_row += 1
            # Make it a table
            worksheet.add_table(
                verdict_row + 2, current_column + 0,
                punishment_row, current_column + 2,
                {
                    'columns': [{'header': "Category"}, {'header': "Subcategory"}, {'header': "Count"}]
                }
            )

            if category_on_one_row:
                current_column += 4
                group_end_rows.append(punishment_row + 2)
            else:
                current_column = 0
                current_start_row = punishment_row + 2

        if category_on_one_row:
            current_start_row = max(group_end_rows)

def main():
    p = argparse.ArgumentParser("get_occupations.py", description="Tool for processing Old Bailey data into a spreadsheet")
    p.add_argument("data_xml_folder", type=str)
    p.add_argument("--min_year", type=int, default=1833)
    p.add_argument("--max_year", type=int, default=1913)
    p.add_argument("--occupation_csv", type=str)
    p.add_argument("--output_excel", type=str)

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
    offence_summaries: Dict[CategorySubcategory, OffenceSummary] = \
        defaultdict(
            lambda: OffenceSummary(
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
                    current_data = offence_summaries[offence_key]

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
    
    # Now finished building offence_summaries
    # print them!
    for offence_key in sorted(offence_summaries.keys()):
        print(offence_key)
        offence_stat = offence_summaries[offence_key]
        print(f"guilty:\t{offence_stat.verdict_categories['guilty']}\tnot guilty:\t{offence_stat.verdict_categories['notGuilty']}")
        print("Verdicts")
        for verdict, n in offence_stat.verdicts.most_common():
            print(f"\t{n}\t|\t{verdict}")
        print("Punishments (guilty verdicts only)")
        for punishment, n in offence_stat.punishments.most_common():
            print(f"\t{n}\t|\t{punishment}")
    # done

    # Create excel sheet if requested
    if args.output_excel:
        writer = pd.ExcelWriter(args.output_excel, engine='xlsxwriter')
        write_summary_sheet(offence_summaries, writer, args.min_year, args.max_year)
        writer.save()

if __name__ == '__main__':
    main()