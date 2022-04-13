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

def write_summary_sheet(summaries: Dict[CategorySubcategory, OffenceSummary], writer: pd.ExcelWriter, stats: List[Tuple[str, int]], category_on_one_row: bool = True):
    # Based on https://datascience.stackexchange.com/a/46451
    workbook = writer.book
    worksheet = workbook.add_worksheet("Summary")
    writer.sheets["Summary"] = worksheet

    # First, write some generic stats
    worksheet.write_string(0, 0, "Offence Summary")
    # Keep track of the first row for the current offences summmary
    current_start_row = 1
    # Write out statistics
    for name, val in stats:
        worksheet.write_string(current_start_row, 0, name)
        worksheet.write_number(current_start_row, 1, val)
        current_start_row += 1

    # Add spacing between statistics and summaries
    current_start_row += 1

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
            worksheet.write_string(current_start_row + 1, current_column + 0, "Verdicts")
            worksheet.write_string(current_start_row + 2, current_column + 0, "Guilty Verdicts: ")
            worksheet.write_number(current_start_row + 2, current_column + 1, offence_summary.verdict_categories['guilty'])
            worksheet.write_string(current_start_row + 3, current_column + 0, "Not Guilty Verdicts: ")
            worksheet.write_number(current_start_row + 3, current_column + 1, offence_summary.verdict_categories['notGuilty'])
            worksheet.write_string(current_start_row + 4, current_column + 0, "Misc Verdicts: ")
            worksheet.write_number(current_start_row + 4, current_column + 1, offence_summary.verdict_categories['miscVerdict'])

            # Write the full verdict breakdown
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

def write_full_sheets(offence_full_infos: Dict[CategorySubcategory, pd.DataFrame], writer: pd.ExcelWriter):
    workbook = writer.book
    for offence_key in sorted(offence_full_infos.keys()):
        offence_sheet_name = f"{offence_key[0]}-{offence_key[1]}"
        if len(offence_sheet_name) > 31:
            old_name = offence_sheet_name
            offence_sheet_name = offence_sheet_name[:31]
            print(f"Shortened sheet name {old_name} to {offence_sheet_name}")
        
        # Add worksheet
        # (old way)
        # df.to_excel(writer, sheet_name=offence_sheet_name, index=False)

        # (new way)
        # Make the sheet manually, write the dataframe out and add a proper table
        worksheet = workbook.add_worksheet(offence_sheet_name)
        writer.sheets[offence_sheet_name] = worksheet
        # https://xlsxwriter.readthedocs.io/working_with_pandas.html
        # write out sheet without header
        # duplicates can show up if e.g. two offences of the same type are charged with a single punishment
        df = offence_full_infos[offence_key].drop_duplicates()
        df.to_excel(writer, sheet_name=offence_sheet_name, startrow=1, startcol=0, header=False, index=False)
        # Add table, which adds its own header
        column_settings = [{'header': column} for column in df.columns]
        (max_row, max_col) = df.shape
        worksheet.add_table(0, 0, max_row, max_col - 1, {'columns': column_settings})


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
    offence_full_infos: Dict[CategorySubcategory, pd.DataFrame] = \
        defaultdict(
            lambda: pd.DataFrame(
                columns = [
                    "trialId", "trialDate", "highSeas",
                    "verdictCategory", "verdictSubcategory",
                    "punishmentCategory", "punishmentSubcategory", "punishmentDescription",
                    "defendantName", "defendantAge", "defendantGender", "defendantOccupation",
                    "defendantWorkingClass", "defendantSkilled",
                ]
            )
        )

    total = 0
    skipped = 0
    corrected = 0
    for date, trials in trials_per_date.items():
        for trial in trials:
            total += 1
            if trial is None:
                skipped += 1
                continue
            elif trial.corrected:
                corrected += 1

            # Count stats for each Offence for each Person in each Charge
            # if a Charge has multiple Offences, 
            # the single Verdict for that Charge counts for all Offences
            # if a Charge has multiple People,
            # the single Verdict for that Charge counts for all Offences for each Person
            # punishments have to be counted per Person
            # if the Verdict is guilty, the punishment for each Person in the Charge is counted for each Offence

            # Update offence full infos
            for charge in trial.charges:
                for offence in charge.offence:
                    offence_key = (offence.category, offence.subcategory)

                    # Generate full info
                    info_dict = {
                        "trialId": [trial.id],
                        "trialDate": [trial.date],
                        "highSeas": [str("high seas" in offence.description.lower())],
                        "verdictCategory": [charge.verdict.category],
                        "verdictSubcategory": [charge.verdict.subcategory]
                    }
                    info_dict.update({
                        f"victimGender{i}": v.gender
                        for i, v in enumerate(offence.victims)
                    })
                    verdict_df = pd.DataFrame(info_dict)
                    for person in charge.defendant:
                        person_df = pd.DataFrame({
                            "defendantName": [person.name],
                            "defendantAge": [person.age],
                            "defendantGender": [person.gender],
                            "defendantOccupation": [
                                person.occupation
                                if isinstance(person.occupation, str) or person.occupation is None
                                else person.occupation.name
                            ],
                            "defendantWorkingClass": [(
                                str(person.occupation.working_class)
                                if isinstance(person.occupation, liboldbailey.process.Occupation)
                                else "None"
                            )],
                            "defendantSkilled": [(
                                str(person.occupation.skilled)
                                if isinstance(person.occupation, liboldbailey.process.Occupation)
                                else "None"
                            )],
                        })
                        if charge.verdict.category == "guilty":
                            punishments = [
                                p
                                for p in trial.punishments.values()
                                if person in p.defendants
                            ]
                        else:
                            # Add an empty punishment, otherwise the join won't produce results
                            punishments = [liboldbailey.process.Punishment(
                                id="",
                                category="Not Punished",
                                subcategory=None,
                                description="",
                                defendants=[]
                            )]
                        punishments_df = pd.DataFrame({
                            "punishmentCategory": [p.category for p in punishments],
                            "punishmentSubcategory": [p.subcategory for p in punishments],
                            "punishmentDescription": [p.description for p in punishments],
                        })
                        # person X punishments = a row for each permutation of person, punishment
                        person_punishments_df = pd.merge(person_df, punishments_df, how="cross")
                        # (person X punishments) X verdict = a row for each permutation of person, punishment with the same verdict info at the front
                        person_punishments_verdict_df = pd.merge(verdict_df, person_punishments_df, how="cross")
                        # Add that data to the full_infos
                        offence_full_infos[offence_key] = pd.concat([
                            offence_full_infos[offence_key],
                            person_punishments_verdict_df
                        ])

                    # Generate summary
                    offence_summary = offence_summaries[offence_key]
                    # count verdicts for each punishment for each defendant, so the summary is consistent with the columns in offence_full_infos.
                    # COUNTIF(<verdict_column>, "guilty") should be == summary.guiltyverdicts
                    for person in charge.defendant:
                        # only count punishments for guilty verdicts
                        if charge.verdict.category == "guilty":
                            punishments = [
                                (p.category, p.subcategory)
                                for p in trial.punishments.values()
                                if person in p.defendants
                            ]
                        else:
                            punishments = [("Not Guilty/Misc", None)]
                        # if multiple punishments, count all of them?
                        offence_summary.punishments.update(
                            punishments
                        )
                        # count each verdict for each punishment
                        offence_summary.verdicts.update([
                            (charge.verdict.category, charge.verdict.subcategory)
                        ] * len(punishments))
                        offence_summary.verdict_categories.update([
                            charge.verdict.category
                        ] * len(punishments))
    
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
        stats = [
            ("Start Year", args.min_year),
            ("End Year", args.max_year),
            ("Total Trials", total),
            ("Malformed Trials (skipped)", skipped),
            ("Malformed Trials (corrected)", corrected),
        ]
        write_summary_sheet(offence_summaries, writer, stats, False)
        write_full_sheets(offence_full_infos, writer)
        writer.save()

if __name__ == '__main__':
    main()