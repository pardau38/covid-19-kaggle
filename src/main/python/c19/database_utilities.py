#!/usr/bin/env python3

import multiprocessing as mp
import os
import sqlite3
import time
from typing import Any, List, Tuple

import pandas as pd
import tqdm
from dateutil import parser
from retry import retry

from c19.file_processing import get_body, read_file
from c19.language_detection import update_languages
from c19.data_cleaner import filter_lines_count


def instanciate_sql_db(db_path: str = "articles_database.sqlite") -> None:
    """
    Create the needed SQLite database.

    Args:
        db_path (str, optional): Path to the DB to be created. Defaults to "articles_database.sqlite".
    """
    if os.path.isfile(db_path):
        os.remove(db_path)
    database = sqlite3.connect(db_path)

    # Storing articles
    articles_table = {
        "paper_doi": "TEXT PRIMARY KEY",
        "date": "DATETIME",
        "body": "TEXT",
        "abstract": "TEXT",
        "title": "TEXT",
        "sha": "TEXT",
        "folder": "TEXT"
    }
    columns = [
        "{0} {1}".format(name, col_type)
        for name, col_type in articles_table.items()
    ]
    command = "CREATE TABLE IF NOT EXISTS articles ({});".format(
        ", ".join(columns))
    database.execute(command)

    # Storing sentences
    sentences_table = {
        "paper_doi": "TEXT",
        "section": "TEXT",
        "raw_sentence": "TEXT",
        "sentence": "TEXT",
        "vector": "TEXT"
    }
    columns = [
        "{0} {1}".format(name, col_type)
        for name, col_type in sentences_table.items()
    ]
    command = "CREATE TABLE IF NOT EXISTS sentences ({});".format(
        ", ".join(columns))
    database.execute(command)
    database.close()


def get_articles_to_insert(articles_df: pd.DataFrame) -> List[Any]:
    """
    Create a list of articles to be inserted.
    Args:
        articles_df (pd.DataFrame): The metadata dataframe (sliced or not).

    Returns:
        List[Any]: A list of tuples (index, article).
    """
    articles = []
    for index, data in articles_df.iterrows():
        articles.append((index, data))
    return articles


@retry(sqlite3.OperationalError, tries=5, delay=2)
def insert_rows(list_to_insert: List[Any],
                table_name: str = "articles",
                db_path: str = "articles_database.sqlite") -> None:
    """
    Insert row into the SQLite database. Retry 5 times if database is locked
    by concurring accesses.

    Args:
        list_to_insert (List[Any]): List of data matching either "articles" or "sentences" table columns.
        table_name (str, optional): The name of the table (articles of sentences). Defaults to "articles".
        db_path (str, optional): Path to the SQLite DB. Defaults to "articles_database.sqlite".

    Raises:
        Exception: Unknown table.
    """
    if table_name == "articles":
        command = "INSERT INTO articles(paper_doi, title, body, abstract, date, sha, folder) VALUES (?, ?, ?, ?, ?, ?, ?)"
    elif table_name == "sentences":
        command = "INSERT INTO sentences(paper_doi, section, raw_sentence, sentence, vector) VALUES (?, ?, ?, ?, ?)"
    else:
        raise Exception(f"Unknown table {table_name}")

    connection = sqlite3.connect(db_path)
    cursor = connection.cursor()
    cursor.executemany(command,
                       list_to_insert)  # This line will be retried if fails
    cursor.close()
    connection.commit()
    connection.close()


def get_article_text(args: List[Tuple[int, pd.Series, str, bool]]) -> None:
    """
    Parse and insert a single article into the SQLite DB. Parallelised method.
    args = [(index, df_line), db_path, data_path]

    Args:
        args (List[Tuple[int, pd.Series, str]]): Index, article and path to the DB.
    """
    data = args[0][1]
    kaggle_data_path = args[1]
    load_body = args[2]
    enable_data_cleaner= args[3]
    # Get body
    if data.has_pdf_parse is True and load_body is True:
        json_file = os.path.join(kaggle_data_path, data.full_text_file,
                                 data.full_text_file, "pdf_json", f"{data.sha}.json")
        try:
            json_data = read_file(json_file)
            body = get_body(json_data=json_data)
            folder = data.full_text_file
        except (FileNotFoundError, KeyError, IndexError):
            body = None
            folder = None
    elif data.has_pmc_xml_parse is True and load_body is True:
        json_file = os.path.join(kaggle_data_path, data.full_text_file,
                                    data.full_text_file, "pmc_json",
                                    f"{data.pmcid}.xml.json")
        try:
            json_data = read_file(json_file)
            body = get_body(json_data=json_data)
            folder = data.full_text_file
        except (FileNotFoundError, KeyError, IndexError):
            body = None
            folder = None
    else:
        body = None
        folder = None
    # Get date
    try:
        date = parser.parse(data.publish_time)
    except Exception:  # Better to get no date than a string of whatever
        date = None 

    #Filter abstract text
    if enable_data_cleaner:
        try:
            if isinstance(data.abstract, str) and len(data.abstract)>10:
                abstract = filter_lines_count(data.abstract)
            else:
                abstract = data.abstract
        except Exception as e:
            abstract = data.abstract
            #print("error cleaning abstract", e)
    else:
        abstract = data.abstract
    # Insert
    raw_data = [
        data.doi, data.title, body, abstract, date, data.sha, folder
    ]
    return raw_data


def get_all_articles_data(
        db_path: str = "articles_database.sqlite") -> List[str]:
    """
    Return all articles data stored in the article table.

    Args:
        db_path (str, optional): Path to the SQLite DB. Defaults to "articles_database.sqlite".

    Returns:
        List[str]: List of article data.
    """
    connection = sqlite3.connect(db_path)
    cursor = connection.cursor()
    cursor.execute("SELECT paper_doi, title, abstract, body FROM articles")
    ids = cursor.fetchall()
    cursor.close()
    connection.close()

    # ids_cleaneds = [id_ for id_ in ids if len(id_) == 1 and id_[0] is not None]
    ids_cleaneds = ids

    return ids_cleaneds


def create_db_and_load_articles(db_path: str = "articles_database.sqlite",
                                kaggle_data_path: str = os.path.join(
                                    os.sep, "kaggle", "input",
                                    "CORD-19-research-challenge"),
                                first_launch: bool = False,
                                load_body: bool = False,
                                run_on_kaggle: bool = False,
                                only_covid: bool = False,
                                enable_data_cleaner:bool = False) -> None:
    """
    Main function to create the DB at first launch.
    Load metadata.csv, try to get body texts and insert everything without pre-processing.

    Args:
        db_path (str, optional): Path to the SQLite file. Defaults to "articles_database.sqlite".
        kaggle_data_path (str, optional): Path to the folder containing Kaggle JSON files.
        load_file (bool, optional): Debug option to prevent to create a new file. Defaults to True.
    """

    if first_launch is False:
        assert os.path.isfile(db_path)
        print(f"DB {db_path} will be used instead.")

    else:
        tic = time.time()

        def select_articles_to_load(kaggle_data_path : str,
                                    run_on_kaggle : bool = False,
                                    only_covid : bool = False) -> pd.DataFrame:
            """
            Select the articles to be inserted in the database

            Args:
                kaggle_data_path (str): The path to the data.
                run_on_kaggle (bool, optional): Determines if the notebook is running on Kaggle, so the DB is limited.
                only_covid (bool, optional): Determines if only COVID-19 articles are to be loaded.

            Returns:
                pd.dataframe: A dataframe with the articles to be inserted.
            """

            # The metadata.csv file will be used to fetch available files
            metadata_df = pd.read_csv(os.path.join(kaggle_data_path, "metadata.csv"), low_memory=False)
            
            # The DOI isn't unique, then let's keep the last version of a duplicated paper
            metadata_df.drop_duplicates(subset=["doi"], keep="last", inplace=True)
            
            # If on Kaggle, only keep latest articles to limit DB size
            if run_on_kaggle is True:
                metadata_df = metadata_df.dropna(axis=0, subset=['abstract'])
                metadata_df['publish_time'] = pd.to_datetime(metadata_df['publish_time'])
                metadata_df["to_keep"] = [True if date.year >= 2019 else False for date in metadata_df['publish_time'].to_list()]
                metadata_df = metadata_df[metadata_df["to_keep"] == True]
            
            # If only covid-19, only keep articles related to it
            if only_covid is True:
                metadata_df = metadata_df.dropna(axis=0, subset=['abstract'])
                metadata_df['publish_time'] = pd.to_datetime(metadata_df['publish_time'])
                metadata_df["to_keep"] = [True if date.year >= 2019 else False for date in metadata_df['publish_time'].to_list()]
                metadata_df = metadata_df[metadata_df["to_keep"] == True]

                abstracts = metadata_df['abstract'].to_list()
                covid_synonyms = ['corona','covid','ncov','sars-cov-2']
                metadata_df["to_keep"] = False
                for synonym in covid_synonyms:
                    metadata_df["to_keep"] += [True if re.search(synonym,abstract) else False for abstract in abstracts]
                metadata_df = metadata_df[metadata_df["to_keep"] == True]            

            # For the moment, we only trained english embedding. See you on 04/16.
            metadata_df = update_languages(metadata_df)
            metadata_df = metadata_df[metadata_df.lang == "En"]
            return metadata_df


        # Load usefull information to be stored: id, title, body, abstract, date, sha, folder
        articles_to_be_inserted = [
            (article, kaggle_data_path, load_body, enable_data_cleaner)
            for article in get_articles_to_insert(select_articles_to_load(kaggle_data_path,run_on_kaggle,only_covid))
        ]
        print(f"{len(articles_to_be_inserted)} articles to be prepared.")

        # Create a new SQLite DB file
        instanciate_sql_db(db_path=db_path)

        # Parallelize articles pre_processing
        tic = time.time()
        pool = mp.Pool(processes=os.cpu_count())
        rows_to_insert = list(
            tqdm.tqdm(pool.imap_unordered(get_article_text,
                                          articles_to_be_inserted),
                      total=len(articles_to_be_inserted),
                      desc="PRE-PROCESSING: "))
        toc = time.time()
        print(
            f"Took {round((toc-tic) / 60, 2)} min to prepare {len(articles_to_be_inserted)} articles for insertion."
        )
        del articles_to_be_inserted
        time.sleep(0.5)

        # And finaly insert
        tic = time.time()
        insert_rows(list_to_insert=rows_to_insert, db_path=db_path)
        toc = time.time()
        print(
            f"Took {round((toc-tic) / 60, 2)} min to insert {len(rows_to_insert)} articles (SQLite DB: {db_path})."
        )


def get_sentences(db_path: str) -> List[Any]:
    """
    Retrieve all sentences from the DB.

    Args:
        db_path (str): Path to the DB.

    Returns:
        List[Any]: List of sentences data.
    """
    connection = sqlite3.connect(db_path)
    cursor = connection.cursor()
    command = "SELECT * FROM sentences WHERE vector IS NOT NULL"
    cursor.execute(command)
    data = cursor.fetchall()
    cursor.close()
    connection.close()

    return data

def get_article(db_path: str, paper_doi):
    """
    Retrieve a paper from the DB using it's DOI.

    Args:
        db_path (str): Path to the DB.

    Returns:
        List[Any]: List of sentences data.
    """
    connection = sqlite3.connect(db_path)
    cursor = connection.cursor()
    command = "SELECT * FROM articles WHERE paper_doi='%s'" % paper_doi
    cursor.execute(command)
    data = cursor.fetchall()
    cursor.close()
    connection.close()

    return data
