"""
the Randomized Control Trial (RCT) robot predicts whether a given
*abstract* (not full-text) describes an RCT.

    title =    '''Does usage of a parachute in contrast to free fall prevent major trauma?: a prospective randomised-controlled trial in rag dolls.'''
    abstract = '''PURPOSE: It is undisputed for more than 200 years that the use of a parachute prevents major trauma when falling from a great height. Nevertheless up to date no prospective randomised controlled trial has proven the superiority in preventing trauma when falling from a great height instead of a free fall. The aim of this prospective randomised controlled trial was to prove the effectiveness of a parachute when falling from great height. METHODS: In this prospective randomised-controlled trial a commercially acquirable rag doll was prepared for the purposes of the study design as in accordance to the Declaration of Helsinki, the participation of human beings in this trial was impossible. Twenty-five falls were performed with a parachute compatible to the height and weight of the doll. In the control group, another 25 falls were realised without a parachute. The main outcome measures were the rate of head injury; cervical, thoracic, lumbar, and pelvic fractures; and pneumothoraxes, hepatic, spleen, and bladder injuries in the control and parachute groups. An interdisciplinary team consisting of a specialised trauma surgeon, two neurosurgeons, and a coroner examined the rag doll for injuries. Additionally, whole-body computed tomography scans were performed to identify the injuries. RESULTS: All 50 falls-25 with the use of a parachute, 25 without a parachute-were successfully performed. Head injuries (right hemisphere p = 0.008, left hemisphere p = 0.004), cervical trauma (p < 0.001), thoracic trauma (p < 0.001), lumbar trauma (p < 0.001), pelvic trauma (p < 0.001), and hepatic, spleen, and bladder injures (p < 0.001) occurred more often in the control group. Only the pneumothoraxes showed no statistically significant difference between the control and parachute groups. CONCLUSIONS: A parachute is an effective tool to prevent major trauma when falling from a great height.'''
    ptyp_is_rct = True

    rct_robot = RCTRobot()
    annotations = rct_robot.annotate(title, abstract, ptyp)

This model was trained on the Cochrane crowd dataset, and validated on the Clinical Hedges dataset
"""

# Authors:  Iain Marshall <mail@ijmarshall.com>
#           Joel Kuiper <me@joelkuiper.com>
#           Byron Wallce <byron.wallace@utexas.edu>

import json
import uuid
import os

import pickle 

import robotsearch
from robotsearch.ml.classifier import MiniClassifier
from sklearn.feature_extraction.text import HashingVectorizer
from robotsearch.parsers import ris

from scipy.sparse import lil_matrix, hstack

import numpy as np
import re
import glob
from sklearn.feature_extraction.text import VectorizerMixin
from sklearn.base import ClassifierMixin
from keras.preprocessing import sequence
from collections import Counter
from keras.models import Sequential
from keras.preprocessing import sequence
from keras.layers import Dense, Dropout, Activation, Lambda, Input, merge, Flatten
from keras.layers import Embedding
from keras.layers import Convolution1D, MaxPooling1D
from keras import backend as K
from keras.models import Model
from keras.regularizers import l2, activity_l2
from keras.models import model_from_json


class KerasVectorizer(VectorizerMixin):    
    def __init__(self, input='content', encoding='utf-8',
                 decode_error='strict', strip_accents=None,
                 lowercase=True, preprocessor=None, tokenizer=None,
                 stop_words=None, token_pattern=r"(?u)\b\w\w+\b",
                 analyzer='word', embedding_inits=None, vocab_map_file=None):
        self.input = input
        self.encoding = encoding
        self.decode_error = decode_error
        self.strip_accents = strip_accents
        self.preprocessor = preprocessor
        self.tokenizer = tokenizer
        self.analyzer = analyzer
        self.lowercase = lowercase
        self.token_pattern = token_pattern
        self.stop_words = stop_words
        self.ngram_range = (1, 1)
        self.embedding_inits = embedding_inits # optional gensim word2vec model
        self.embedding_dim = embedding_inits.syn0.shape[1] if embedding_inits else None
        with open(vocab_map_file, 'rb') as f:
            self.vocab_map = pickle.load(f)
        
    def transform(self, raw_documents, maxlen=400):
        """
        returns lists of integers
        """
        analyzer = self.build_analyzer()
        int_lists = [[1]+[self.vocab_map.get(w, 2) for w in analyzer(t)] for t in raw_documents]
        # 0 = pad, 1 = start, 2 = OOV
        return sequence.pad_sequences(int_lists, maxlen=maxlen)


def get_model(json_filename, weights_filename):
    with open(json_filename, 'r') as f:
        json_string = json.load(f)
    model = model_from_json(json_string)
    model.load_weights(weights_filename)
    return model


class RCTRobot:

    def __init__(self):
        self.svm_clf = MiniClassifier(os.path.join(robotsearch.DATA_ROOT, 'rct/rct_svm_weights.npz'))

        

        cnn_weight_files = glob.glob(os.path.join(robotsearch.DATA_ROOT, 'rct/*.h5'))
        json_filename = os.path.join(robotsearch.DATA_ROOT, 'rct/rct_cnn_structure.json')
        self.cnn_clfs = [get_model(json_filename, cnn_weight_file) for cnn_weight_file in cnn_weight_files]        
        self.svm_vectorizer = HashingVectorizer(binary=False, ngram_range=(1, 1), stop_words='english')
        self.cnn_vectorizer = KerasVectorizer(vocab_map_file=os.path.join(robotsearch.DATA_ROOT, 'rct/rct_cnn_vocab_map.pck'))

        self.scale_constants = {"svm": {"mean": -0.75481403525485891,
                                        "std": 0.7812955939364481,
                                        "weight": 10.},
                                "ptyp": {"mean": 0.055155532891381948,
                                        "std": 0.22828359573751594,
                                        "weight": 1.},
                                "cnn": {"mean": 0.15549565997665432,
                                        "std": 0.22064840347497616,
                                        "weight": 1.}} # weighted in mean since we use only 1 model (since produces near identical results to binning 10)
 
        self.thresholds = {"svm": {"precise": 1.9487503268,
                                   "sensitive": -0.12860007792},
                           "svm_ptyp": {"precise": 4.01565491262,
                                        "sensitive": -0.014853014584},
                           "cnn": {"precise": 2.0417000432,
                                   "sensitive": -0.311928636661},
                           "cnn_ptyp": {"precise": 3.58216450739,
                                        "sensitive": -0.38400452513},
                            "svm_cnn": {"precise": 2.01457242432,
                                        "sensitive": -0.275235475372},
                            "svm_cnn_ptyp": {"precise": 3.59886540373,
                                            "sensitive": -0.294982870378}}

        # All precise models have been calibrated to 97.6% sensitivity
        # All sensitive models have been calibrated to 99.1% sensitivity

                                        




    def filter_articles(self, ris_data, filter_class="svm", filter_type='precise'):

        simplified = [ris.simplify(article) for article in ris_data]

        X_ti_str = [article.get('title', '') for article in simplified]
        X_ab_str = ['{}\n\n{}'.format(article.get('title', ''), article.get('abstract', '')) for article in simplified]    

        if "svm" in filter_class:

            X_ti = lil_matrix(self.svm_vectorizer.transform(X_ti_str))
            X_ab = lil_matrix(self.svm_vectorizer.transform(X_ab_str))

            svm_preds = self.svm_clf.decision_function(hstack([X_ti, X_ab]))
            svm_scale =  (svm_preds - self.scale_constants['svm']['mean']) / self.scale_constants['svm']['std']

        if "ptyp" in filter_class:
            ptyp = np.array([(article.get('rct_ptyp')==True)*1. for article in simplified])
            ptyp_scale =  (ptyp - self.scale_constants['ptyp']['mean']) / self.scale_constants['ptyp']['std']

        if "cnn" in filter_class:
            X_cnn = self.cnn_vectorizer.transform(X_ab_str)            
            cnn_preds = [clf.predict(X_cnn).T[0] for clf in self.cnn_clfs]
            
        
            cnn_preds = np.vstack(cnn_preds)
            
            cnn_scale =  (cnn_preds - self.scale_constants['cnn']['mean']) / self.scale_constants['cnn']['std']

        if filter_class == "svm":
            y_preds = svm_scale
        elif filter_class == "svm_ptyp":
            y_preds = svm_scale + ptyp_scale
        elif filter_class == "ptyp":
            y_preds = ptyp_scale
        elif filter_class == "svm_cnn_ptyp":
            weights = [self.scale_constants['svm']['weight']] + ([self.scale_constants['cnn']['weight']] * len(self.cnn_clfs))
            y_preds = np.average(np.vstack([cnn_scale, svm_scale]), axis=0, weights=weights) + ptyp_scale

        
        return [article for article, y_pred in zip(ris_data, y_preds) if y_pred > self.thresholds[filter_class][filter_type]]

    



