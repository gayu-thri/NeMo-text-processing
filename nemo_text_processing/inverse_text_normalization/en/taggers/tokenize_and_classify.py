# Copyright (c) 2021, NVIDIA CORPORATION.  All rights reserved.
# Copyright 2015 and onwards Google, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import logging
import os

import pynini
from nemo_text_processing.inverse_text_normalization.en.taggers.cardinal import CardinalFst
from nemo_text_processing.inverse_text_normalization.en.taggers.date import DateFst
from nemo_text_processing.inverse_text_normalization.en.taggers.decimal import DecimalFst
from nemo_text_processing.inverse_text_normalization.en.taggers.electronic import ElectronicFst
from nemo_text_processing.inverse_text_normalization.en.taggers.measure import MeasureFst
from nemo_text_processing.inverse_text_normalization.en.taggers.money import MoneyFst
from nemo_text_processing.inverse_text_normalization.en.taggers.profane import ProfaneFst
from nemo_text_processing.inverse_text_normalization.en.taggers.ordinal import OrdinalFst
from nemo_text_processing.inverse_text_normalization.en.taggers.punctuation import PunctuationFst
from nemo_text_processing.inverse_text_normalization.en.taggers.telephone import TelephoneFst
from nemo_text_processing.inverse_text_normalization.en.taggers.time import TimeFst
from nemo_text_processing.inverse_text_normalization.en.taggers.whitelist import WhiteListFst
from nemo_text_processing.inverse_text_normalization.en.taggers.word import WordFst
from nemo_text_processing.text_normalization.en.graph_utils import (
    INPUT_LOWER_CASED,
    GraphFst,
    delete_extra_space,
    delete_space,
    generator_main,
)
from pynini.lib import pynutil


class ClassifyFst(GraphFst):
    """
    Final class that composes all other classification grammars. This class can process an entire sentence, that is lower cased.
    For deployment, this grammar will be compiled and exported to OpenFst Finite State Archive (FAR) File.
    More details to deployment at NeMo/tools/text_processing_deployment.

    Args:
        input_case: accepting either "lower_cased" or "cased" input.
        cache_dir: path to a dir with .far grammar file. Set to None to avoid using cache.
        overwrite_cache: set to True to overwrite .far files
        whitelist: path to a file with whitelist replacements
        filter_profanity: set to False to disable profanity filtering
    """

    def __init__(
        self,
        input_case: str = INPUT_LOWER_CASED,
        cache_dir: str = None,
        overwrite_cache: bool = False,
        whitelist: str = None,
        filter_profanity: bool = True,
    ):
        super().__init__(name="tokenize_and_classify", kind="classify")

        far_file = None
        if cache_dir is not None and cache_dir != "None":
            os.makedirs(cache_dir, exist_ok=True)
            far_file = os.path.join(cache_dir, f"en_itn_{input_case}.far")
        if not overwrite_cache and far_file and os.path.exists(far_file):
            self.fst = pynini.Far(far_file, mode="r")["tokenize_and_classify"]
            logging.info(f"ClassifyFst.fst was restored from {far_file}.")
        else:
            logging.info(f"Creating ClassifyFst grammars.")
            cardinal = CardinalFst(input_case=input_case)
            cardinal_graph = cardinal.fst

            ordinal = OrdinalFst(cardinal, input_case=input_case)
            ordinal_graph = ordinal.fst

            decimal = DecimalFst(cardinal, input_case=input_case)
            decimal_graph = decimal.fst

            measure_graph = MeasureFst(cardinal=cardinal, decimal=decimal, input_case=input_case).fst
            date_graph = DateFst(ordinal=ordinal, input_case=input_case).fst
            word_graph = WordFst().fst
            time_graph = TimeFst(input_case=input_case).fst
            money_graph = MoneyFst(cardinal=cardinal, decimal=decimal, input_case=input_case).fst
            whitelist_graph = WhiteListFst(input_file=whitelist, input_case=input_case).fst
            punct_graph = PunctuationFst().fst
            electronic_graph = ElectronicFst(input_case=input_case).fst
            telephone_graph = TelephoneFst(cardinal, input_case=input_case).fst
            profane_graph = ProfaneFst(input_case=input_case).fst

            classify = (
                pynutil.add_weight(whitelist_graph, 1.01)
                | pynutil.add_weight(time_graph, 1.1)
                | pynutil.add_weight(date_graph, 1.09)
                | pynutil.add_weight(decimal_graph, 1.1)
                | pynutil.add_weight(measure_graph, 1.1)
                | pynutil.add_weight(cardinal_graph, 1.1)
                | pynutil.add_weight(ordinal_graph, 1.09)
                | pynutil.add_weight(money_graph, 1.1)
                | pynutil.add_weight(telephone_graph, 1.1)
                | pynutil.add_weight(electronic_graph, 1.1)
                | pynutil.add_weight(word_graph, 100)
            )
            # Attempts to filter profane words only if `filter_profanity` field is set to True
            if filter_profanity:
                classify = (pynutil.add_weight(profane_graph, 0.0001) | classify).optimize()
                

            punct = pynutil.insert("tokens { ") + pynutil.add_weight(punct_graph, weight=1.1) + pynutil.insert(" }")
            token = pynutil.insert("tokens { ") + classify + pynutil.insert(" }")
            token_plus_punct = (
                pynini.closure(punct + pynutil.insert(" ")) + token + pynini.closure(pynutil.insert(" ") + punct)
            )

            graph = token_plus_punct + pynini.closure(delete_extra_space + token_plus_punct)
            graph = delete_space + graph + delete_space

            self.fst = graph.optimize()

            if far_file:
                generator_main(far_file, {"tokenize_and_classify": self.fst})
                logging.info(f"ClassifyFst grammars are saved to {far_file}.")
