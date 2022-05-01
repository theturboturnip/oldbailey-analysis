import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any, DefaultDict, Dict, Iterable, List, Pattern, Tuple, Union
import pandas as pd

import re

def generate_units() -> Dict[str, float]:
    # Assume month = 4.5 weeks = 31 days
    unit_to_month = {
        "day": 1.0/31.0,
        "week": 1.0/4.5,
        "month": 1.0,
        "year": 12.0,
        # year -> tear is a common mispelling
        "tear": 12.0,
    }

    return unit_to_month

def generate_unit_re_str(units: Iterable[str]) -> Pattern:
    return "(" + "|".join(units) + ")"

# The sentences have the numbers written out in english
# e.g. 28 => "Twenty-Eight"
# Create a mapping of english to numbers
def generate_number_mappings() -> Dict[str, int]:
    # Just write them out manually lol - only like thirty required
    str_to_num = {
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
        "ten": 10,
        "eleven": 11,
        "twelve": 12,
        "thirteen": 13,
        "fourteen": 14,
        "fifteen": 15,
        "sixteen": 16,
        "seventeen": 17,
        "eighteen": 18,
        "nineteen": 19,

        "twenty": 20,
        "twenty-one": 21,
        "twenty-two": 22,
        "twenty-three": 23,
        "twenty-four": 24,
        "twenty-five": 25,
        "twenty-six": 26,
        "twenty-seven": 27,
        "twenty-eight": 28,
        "twenty-nine": 29,
        "thirty": 30,
    }
    # Some are categorized with actual numbers - add those
    str_to_num.update({
        str(i): i
        for i in range(1, 31)
    })

    return str_to_num

def generate_num_regex_str(num_strs: Iterable[str]) -> str:
    return "(" + "|".join(num_strs) + ")"

@dataclass
class ParsedSentence:
    original_sentence: str
    occurrences: int

    extracted_phrase: str
    phrase_num: int
    phrase_unit: str

    approx_months: float

@dataclass
class SentenceParseError:
    original_sentence: str
    occurrences: int
    err: str

ParsedSentenceResult = Union[ParsedSentence, SentenceParseError]

@dataclass
class Helpers:
    # Converts an english
    str_to_num: Dict[str, int]
    # Regex matching a single number + unit combination
    num_unit_re: Pattern
    
    # Dictionary matching valid units to numbers of months
    unit_to_month: Dict[str, int]
    # Regex matching exactly one unit
    unit_re: Pattern

    # Regex matching "Confined X units"
    # Used as a special case for "Confined X units; Y units solitary" which would otherwise confuse the parser
    confined_x_y_re: Pattern

    @staticmethod
    def generate() -> 'Helpers':
        unit_to_month = generate_units()
        unit_re_str = generate_unit_re_str(unit_to_month.keys())
        unit_re = re.compile(unit_re_str, flags=re.IGNORECASE)

        str_to_num = generate_number_mappings()
        num_unit_str = generate_num_regex_str(str_to_num.keys()) + "\s+" + unit_re_str
        num_unit_re = re.compile(num_unit_str, re.IGNORECASE)

        confined_x_y_re = re.compile(r"^Confined\s+" + num_unit_str, re.IGNORECASE)
        print(r"^Confined\s+" + num_unit_str)

        return Helpers(
            str_to_num=str_to_num,
            num_unit_re=num_unit_re,

            unit_to_month=unit_to_month,
            unit_re=unit_re,

            confined_x_y_re=confined_x_y_re,
        )


def parse_confined_x_y_sentence(sentence: str, occurrences: int, helpers: Helpers) -> ParsedSentenceResult:
    # Helper function for returning errors
    def error(err: str) -> SentenceParseError:
        print(f"[ERR] {sentence} : {err}")
        return SentenceParseError(original_sentence=sentence, occurrences=occurrences, err=err)

    match = helpers.confined_x_y_re.search(sentence)
    if not match:
        return error("Found multiple units, didn't fit Confined X; Y format")

    extracted_phrase = match.group(0)
    phrase_num = helpers.str_to_num[match.group(1).lower()]
    phrase_unit = match.group(2).lower()
    approx_months = helpers.unit_to_month[phrase_unit] * phrase_num

    return ParsedSentence(
        original_sentence=sentence,
        occurrences=occurrences,

        extracted_phrase=extracted_phrase,
        phrase_num=phrase_num,
        phrase_unit=phrase_unit,
        approx_months=approx_months
    )

# Parse a single sentence.
# If we could successfully identify a single length (e.g. "twenty-eight years") returns a ParsedSentence
# else returns a SentenceParseError with more details
def parse_sentence(sentence: str, occurrences: int, helpers: Helpers) -> ParsedSentenceResult:
    # Helper function for returning errors
    def error(err: str) -> SentenceParseError:
        print(f"[ERR] {sentence} : {err}")
        return SentenceParseError(original_sentence=sentence, occurrences=occurrences, err=err)

    # Try to find a unit
    # if we find 0 or 2+ units, reject
    units = helpers.unit_re.findall(sentence)
    if not units:
        return error(f"Found no units")
    if len(units) > 1:
        if sentence.lower().startswith("confined"):
            return parse_confined_x_y_sentence(sentence, occurrences, helpers)
        return error(f"Found multiple units {units}, parse would be ambiguous")

    # There is exactly one unit
    # Match against a stringified number
    match = helpers.num_unit_re.search(sentence)
    if not match:
        return error(f"Found single unit {units} but couldn't match with a number")
    
    extracted_phrase = match.group(0)
    phrase_num = helpers.str_to_num[match.group(1).lower()]
    phrase_unit = match.group(2).lower()
    approx_months = helpers.unit_to_month[phrase_unit] * phrase_num

    return ParsedSentence(
        original_sentence=sentence,
        occurrences=occurrences,

        extracted_phrase=extracted_phrase,
        phrase_num=phrase_num,
        phrase_unit=phrase_unit,
        approx_months=approx_months
    )

# Return a list for a given parsed sentence matching the pattern
# [sentence, occurrences, extracted_phrase, phrase_num, phrase_unit, approx_months, err]
def sentence_to_row(r: ParsedSentenceResult) -> List[Any]:
    if isinstance(r, ParsedSentence):
        return [
            r.original_sentence,
            r.occurrences,
            r.extracted_phrase,
            r.phrase_num,
            r.phrase_unit,
            r.approx_months,
            None
        ]
    else:
        return [
            r.original_sentence,
            r.occurrences,
            None,
            None,
            None,
            None,
            r.err
        ]

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output_excel", type=Path)

    args = parser.parse_args()

    assert str(args.output_excel).endswith(".xlsx")

    with open(args.input, "r") as f:
        data = pd.read_csv(f, names=["sentence","occurrences"], usecols=[0,1])

    data = data.dropna()
    data.drop(data[data["sentence"] == "Grand Total"].index, inplace=True)
    print(data)

    # Generate helper dictionaries and regexes
    helpers = Helpers.generate()

    sentence_results: List[ParsedSentenceResult] = [
        parse_sentence(sentence, occurrences, helpers)
        for sentence, occurrences in zip(data['sentence'], data['occurrences'])
    ]

    total_occurrences = data['occurrences'].sum()
    missed_occurrences = sum(
        r.occurrences
        for r in sentence_results
        if isinstance(r, SentenceParseError)
    )
    missed_confined_occurrences = sum(
        r.occurrences
        for r in sentence_results
        if isinstance(r, SentenceParseError) and r.original_sentence.startswith("Confined")
    )
    confined_err_rows = sum(1 for r in sentence_results if isinstance(r, SentenceParseError) and r.original_sentence.startswith("Confined"))
    n_errs = sum(1 for r in sentence_results if isinstance(r, SentenceParseError))
    print(f"Missed Occurrences\t{missed_occurrences}")
    print(f"Total Occurrences\t{total_occurrences}")
    print(f"Percentage Missed\t{missed_occurrences*100.0/total_occurrences}%")
    print(f"Missed Confined Occurrences\t{missed_confined_occurrences}")
    print(f"Total Confined Occurrences\t{total_occurrences}")
    print(f"Percentage Missed\t{missed_confined_occurrences*100.0/total_occurrences}%")
    print(f"Num Errors\t{n_errs}")
    print(f"Total Rows\t{len(sentence_results)}")
    print(f"Percentage Missed\t{n_errs*100.0/len(sentence_results)}%")
    print(f"Num Confined Errors\t{confined_err_rows}")
    print(f"Total Rows\t{len(sentence_results)}")
    print(f"Percentage Missed\t{confined_err_rows*100.0/len(sentence_results)}%")

    output_data = {
        i: sentence_to_row(r)
        for i, r in enumerate(sentence_results)
    }
    output_df = pd.DataFrame.from_dict(output_data, orient='index', columns=[
        "Sentence",
        "Occurrences",
        "Length - Phrase",
        "Length - Number",
        "Length - Unit",
        "Months (Approx.)",
        "Parse Error"
    ])


    # Write out the dataframe
    writer = pd.ExcelWriter(args.output_excel, engine='xlsxwriter')
    workbook = writer.book
    offence_sheet_name = f"Sentence Mapping"

    # Make the sheet manually, write the dataframe out and add a proper table
    worksheet = workbook.add_worksheet(offence_sheet_name)
    writer.sheets[offence_sheet_name] = worksheet
    # https://xlsxwriter.readthedocs.io/working_with_pandas.html
    # write out sheet without header
    df = output_df
    df.to_excel(writer, sheet_name=offence_sheet_name, startrow=1, startcol=0, header=False, index=False)
    # Add table, which adds its own header
    column_settings = [{'header': column} for column in df.columns]
    (max_row, max_col) = df.shape
    worksheet.add_table(0, 0, max_row, max_col - 1, {'columns': column_settings})
    writer.save()