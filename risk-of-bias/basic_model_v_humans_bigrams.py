# Runs a basic model
# Models each domain in turn using SVMs with L2 regularisation + bag of words
# Uses feature limiting to exclude features with < 2 appearances across the corpus

# 1 fold, and versus humans and baseline
# same as basic, but uses bigrams and unigrams

from cochranenlp.experiments import riskofbias
from cochranenlp.ml import modhashvec
from cochranenlp.output import metrics, outputnames


import numpy as np

from sklearn.cross_validation import KFold
from sklearn.grid_search import GridSearchCV
from sklearn.linear_model import SGDClassifier

import sys
import os
import time

def main(out_dir="results"):
    model_metrics = metrics.BinaryMetricsRecorder(domains=riskofbias.CORE_DOMAINS)
    stupid_metrics = metrics.BinaryMetricsRecorder(domains=riskofbias.CORE_DOMAINS)
    human_metrics = metrics.BinaryMetricsRecorder(domains=riskofbias.CORE_DOMAINS)


    # parse the risk of bias data from Cochrane
    data = riskofbias.RoBData(test_mode=False)
    data.generate_data(doc_level_only=True, skip_small_files=True)

    # filter the data by Document
    filtered_data = riskofbias.DocFilter(data)

    # get the uids of the desired training set
    # (for this experiment those which appear in only one review)

    uids_all = filtered_data.get_ids(pmid_instance=0) # those with 1 or more assessment (i.e. all)
    uids_double_assessed = filtered_data.get_ids(pmid_instance=1) # those with 2 (or more) assessments (to hide for training)

    uids_train = np.setdiff1d(uids_all, uids_double_assessed)

    # we need different test ids for each domain
    # (since we're testing on studies with more than one RoB assessment for *each domain*)

    uids_test = {}
    for domain in riskofbias.CORE_DOMAINS:

        # print "%d docs obtained for domain: %s" % (len(uids), domain)

        tuned_parameters = {"alpha": np.logspace(-2, 2, 10)}
        clf = GridSearchCV(SGDClassifier(loss="hinge", penalty="L2"), tuned_parameters, scoring='f1')

        # no_studies = len(uids)

        X_train_d, y_train = filtered_data.Xy(uids_train, domain=domain, pmid_instance=0)

        # get domain test ids
        # (i.e. the double assessed trials, which have a judgement for the current domain in
        #   *both* the 0th and 1st review)
        uids_domain_all = filtered_data.get_ids(pmid_instance=0, filter_domain=domain)
        uids_domain_double_assessed = filtered_data.get_ids(pmid_instance=1, filter_domain=domain)
        uids_test_domain = np.intersect1d(uids_domain_all, uids_domain_double_assessed)


        X_test_d, y_test = filtered_data.Xy(uids_test_domain, domain=domain, pmid_instance=0)

        X_ignore, y_human = filtered_data.Xy(uids_test_domain, domain=domain, pmid_instance=1)
        X_ignore = None # don't need this bit


        vec = modhashvec.InteractionHashingVectorizer(norm=None, non_negative=True, binary=True, ngram_range=(1, 2), n_features=2**24)
        # n_features increased from the default (2^20), since with bigrams added
        # in the features were colliding too much, and then *none* were removed
        # with the low bar setting

        X_train = vec.fit_transform(X_train_d, low=2)
        X_test = vec.transform(X_test_d)

        clf.fit(X_train, y_train)

        y_preds = clf.predict(X_test)

        model_metrics.add_preds_test(y_preds, y_test, domain=domain)
        human_metrics.add_preds_test(y_human, y_test, domain=domain)
        stupid_metrics.add_preds_test([1] * len(y_test), y_test, domain=domain)

    model_metrics.save_csv(os.path.join(out_dir, outputnames.filename(label="model")))
    stupid_metrics.save_csv(os.path.join(out_dir, outputnames.filename(label="stupid-baseline")))
    human_metrics.save_csv(os.path.join(out_dir, outputnames.filename(label="human-performance")))


if __name__ == '__main__':
    args = sys.argv
    if len(args) > 1:
        print "output directory: %s" % args[1]
        main(out_dir=args[1])
    else:
        main()