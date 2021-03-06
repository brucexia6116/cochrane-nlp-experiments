# Runs a multitask model
# Models all domains together using SVMs with L2 regularisation + bag of words
# Uses feature limiting to exclude features with < 2 appearances across the corpus

# 1 fold, and versus humans and baseline
# uses bigrams and unigrams

from cochranenlp.experiments import riskofbias
from cochranenlp.ml import modhashvec
from cochranenlp.output import metrics, outputnames

from cochranenlp.textprocessing.tokenizer import sent_tokenizer

import numpy as np

from sklearn.cross_validation import KFold
from sklearn.grid_search import GridSearchCV
from sklearn.linear_model import SGDClassifier

import sys
import os
import time
import pdb

def main(out_dir="results"):

    model_metrics = metrics.BinaryMetricsRecorder(domains=riskofbias.CORE_DOMAINS)
    stupid_metrics = metrics.BinaryMetricsRecorder(domains=riskofbias.CORE_DOMAINS)
    human_metrics = metrics.BinaryMetricsRecorder(domains=riskofbias.CORE_DOMAINS)

    # parse the risk of bias data from Cochrane
    print "risk of bias data!"
    data = riskofbias.RoBData(test_mode=False)
    data.generate_data(doc_level_only=False)

    # filter the data by Document
    filtered_data = riskofbias.DocFilter(data)

    # get the uids of the desired training set
    # (for this experiment those which appear in only one review)

    uids_all = filtered_data.get_ids(pmid_instance=0) # those with 1 or more assessment (i.e. all)
    uids_double_assessed = filtered_data.get_ids(pmid_instance=1) # those with 2 (or more) assessments (to hide for training)

    uids_train = np.setdiff1d(uids_all, uids_double_assessed)


    ###
    ###    sentence prediction
    ###

    # The first stage is to make the sentence prediction model using the
    #   training data set
    #


    print "First, making sentence prediction model"

    sent_docs = riskofbias.SentFilter(data)

    sent_models = {} #where the key is the domain name

    sent_vec = modhashvec.InteractionHashingVectorizer(norm=None, non_negative=True, binary=True, ngram_range=(1, 2), n_features=2**24) # hashing vectorizer so doesn't change per domain in terms of feature space

    for domain in riskofbias.CORE_DOMAINS:

        sent_uids = np.intersect1d(uids_train, np.array(sent_docs.get_ids(filter_domain=domain)))
        no_studies = len(sent_uids)

        kf = KFold(no_studies, n_folds=5, shuffle=False)

        print "%d docs obtained for domain: %s" % (no_studies, domain)


        tuned_parameters = {"alpha": np.logspace(-4, -1, 5), "class_weight": [{1: i, -1: 1} for i in np.logspace(-1, 1, 5)]}
        clf = GridSearchCV(SGDClassifier(loss="hinge", penalty="L2"), tuned_parameters, scoring='recall')

        X_train_d, y_train = sent_docs.Xy(sent_uids, domain=domain)

        

        X_train = sent_vec.fit_transform(X_train_d, low=2)
        
        clf.fit(X_train, y_train)

        sent_models[domain] = clf.best_estimator_
        # import pdb; pdb.set_trace()

    





    # we need different test ids for each domain
    # (since we're testing on studies with more than one RoB assessment for *each domain*)

    docs = riskofbias.MultiTaskDocFilter(data)

    tuned_parameters = {"alpha": np.logspace(-4, -1, 10)}
    clf = GridSearchCV(SGDClassifier(loss="hinge", penalty="L2"), tuned_parameters, scoring='f1')

    X_train_d, y_train, i_train = docs.Xyi(uids_train, pmid_instance=0)

    # add interaction features (here both domain + high prob sentences)

    interactions = {domain:[] for domain in riskofbias.CORE_DOMAINS}

    high_prob_sents = []

    for doc_text, doc_domain in zip(X_train_d, i_train):

        doc_sents = sent_tokenizer.tokenize(doc_text)
        doc_sents_X = sent_vec.transform(doc_sents)

        doc_sents_preds = sent_models[doc_domain].predict(doc_sents_X)

        high_prob_sents.append(" ".join([sent for sent, sent_pred in zip(doc_sents, doc_sents_preds) if sent_pred==1]))

        print "high prob sents:"

        from collections import Counter
        prob_count = Counter(list(doc_sents_preds))
        print prob_count
        



        for domain in riskofbias.CORE_DOMAINS:
            if domain == doc_domain:
                interactions[domain].append(True)
            else:
                interactions[domain].append(False)

    vec = modhashvec.ModularVectorizer(norm=None, non_negative=True, binary=True, ngram_range=(1, 2), n_features=2**26) # since multitask + bigrams = huge feature space
    vec.builder_clear()

    
    vec.builder_add_docs(X_train_d, low=10) # add base features

    # print high_prob_sents

    for domain in riskofbias.CORE_DOMAINS:
        
        print np.sum(interactions[domain]), "/", len(interactions[domain]), "added for", domain
        vec.builder_add_docs(X_train_d, interactions=interactions[domain], prefix=domain+"-i-", low=2) # then add interactions


    vec.builder_add_docs(high_prob_sents, prefix="-s-", low=2)
    

    X_train = vec.builder_fit_transform()
    
    clf.fit(X_train, y_train)

    # Test on each domain in turn

    for domain in riskofbias.CORE_DOMAINS:

        uids_domain_all = filtered_data.get_ids(pmid_instance=0, filter_domain=domain)
        uids_domain_double_assessed = filtered_data.get_ids(pmid_instance=1, filter_domain=domain)
        uids_test_domain = np.intersect1d(uids_domain_all, uids_domain_double_assessed)


        X_test_d, y_test = filtered_data.Xy(uids_test_domain, domain=domain, pmid_instance=0)

        X_ignore, y_human = filtered_data.Xy(uids_test_domain, domain=domain, pmid_instance=1)
        X_ignore = None # don't need this bit

        #
        #   get high prob sents from test data
        #

        high_prob_sents =[]
        for doc_text in X_test_d:

            doc_sents = sent_tokenizer.tokenize(doc_text)
            doc_sents_X = sent_vec.transform(doc_sents)

            doc_sents_preds = sent_models[domain].predict(doc_sents_X)

            high_prob_sents.append(" ".join([sent for sent, sent_pred in zip(doc_sents, doc_sents_preds) if sent_pred==1]))



        # build up test vector

        vec.builder_clear()
        vec.builder_add_docs(X_test_d) # add base features
        vec.builder_add_docs(X_test_d, prefix=domain+'-i-') # add interactions
        vec.builder_add_docs(high_prob_sents, prefix="-s-")
    
        X_test = vec.builder_transform()

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
