import re

import numpy as np
import pandas as pd
from sklearn.metrics import f1_score
from tqdm import tqdm

from metrics import macro_f1, precision_at_k, recall_at_k
from utils import log
from utils.utils import Timer, dump_log


def evaluate(config, model, dataset_loader, eval_metric, split='val', dump=True):
    timer = Timer()
    eval_metric.clear()
    progress_bar = tqdm(dataset_loader)

    for idx, batch in enumerate(progress_bar):
        batch_labels = batch['label']
        predict_results = model.predict(batch)
        batch_label_scores = predict_results['scores']

        batch_labels = batch_labels.cpu().detach().numpy()
        batch_label_scores = batch_label_scores.cpu().detach().numpy()
        eval_metric.add_batch(batch_labels, batch_label_scores)

    log.info(f'Time for evaluating {split} set = {timer.time():.2f} (s)')
    print(eval_metric)
    metrics = eval_metric.get_metrics()
    if dump:
        dump_log(config, metrics, split)

    return metrics


class FewShotMetrics():
    def __init__(self, config, dataset, few_shot_limit=5):
        # if dataset does not have train in the test mode?

        # test_labels = np.hstack([instance['label']
        #                          for instance in dataset['test']])
        # train_labels = np.hstack([instance['label']
        #                           for instance in dataset['train']])

        self.config = config
        self.num_class = config.num_class
        # get ALL, Z, F, S
        # unique, counts = np.unique(train_labels, return_counts=True)
        # self.frequent_labels_idx = unique[counts > few_shot_limit].astype(int).tolist()
        # self.few_shot_labels_idx = unique[counts <= few_shot_limit].astype(int).tolist()
        # self.zero_shot_labels_idx = list(set(test_labels) - set(train_labels))

        # label groups
        self.label_groups = [[list(range(self.num_class)), 'ALL']]
        # if len(self.few_shot_labels_idx) > 0:
            # self.label_groups.extend([
                # [self.frequent_labels_idx, 'S'],
                # [self.few_shot_labels_idx, 'F'],
                # [self.zero_shot_labels_idx, 'Z']
            # ])

        self.clear()

    def clear(self):
        self.y_true = []
        self.y_pred = []

    def add(self, y_true, y_pred):
        self.y_true.append(y_true)
        self.y_pred.append(y_pred)

    def add_batch(self, y_true, y_pred):
        self.y_true.append(y_true)
        self.y_pred.append(y_pred)

    def filter_instances(self, label_idxs, y_true, y_pred):
        """1. Instances that do not contains labels idxs are removed
           2. Labels that do not contains in the label idxs are removed
        """
        mask_np = np.zeros(self.num_class)
        mask_np[label_idxs] = 1

        valid_instances_idxs = list()
        for i, y in enumerate(y_true):
            if (y * mask_np).sum() > 0:
                valid_instances_idxs.append(i)
        return y_true[valid_instances_idxs][:, label_idxs], y_pred[valid_instances_idxs][:, label_idxs]

    def eval(self, y_true, y_pred, threshold=0.5):
        results = []

        for group_idxs, group_name in self.label_groups:
            result = {'Label Group': group_name, 'Label Size': len(group_idxs)}
            target_y_true, target_y_pred = self.filter_instances(
                group_idxs, y_true, y_pred)
            result['# Instance'] = len(target_y_true)

            # micro/macro f1 of the target groups
            result['Micro-F1'] = f1_score(y_true=target_y_true, y_pred=target_y_pred > threshold, average='micro')
            # result['Macro-F1'] = f1_score(y_true=target_y_true, y_pred=target_y_pred > threshold, average='macro')
            # result['Micro-F1'] = micro_f1((target_y_pred > threshold).ravel(), target_y_true.ravel())
            result['Macro-F1'] = macro_f1(target_y_true, target_y_pred > threshold)

            # find all metric starts with P(Precition) or R(Recall)
            pattern = re.compile('(?:P|R)@\d+')
            for metric in self.config.monitor_metrics:
                for pr_metric in re.findall(pattern, metric):
                    metric_type, top_k = pr_metric.split('@')
                    top_k = int(top_k)
                    metric_at_k = precision_at_k(target_y_true, target_y_pred, k=top_k) if metric_type == 'P' \
                                    else recall_at_k(target_y_true, target_y_pred, k=top_k)
                    result[pr_metric] = metric_at_k

            results.append(result)

        return results

    def get_metrics(self):
        y_true = np.vstack(self.y_true)
        y_pred = np.vstack(self.y_pred)
        return self.eval(y_true, y_pred)

    def __repr__(self):
        results = self.get_metrics()
        df = pd.DataFrame(results).applymap(
            lambda x: f'{x * 100:.4f}' if isinstance(x, (np.floating, float)) else x)
        return df.to_markdown(index=False)
