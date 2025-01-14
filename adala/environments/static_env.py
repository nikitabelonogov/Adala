import pandas as pd
import numpy as np
from pydantic import Field
from typing import Optional, Dict, Union, Callable
from adala.utils.internal_data import (
    InternalDataFrame,
    InternalSeries,
    InternalDataFrameConcat,
)
from adala.utils.matching import fuzzy_match
from adala.skills.skillset import SkillSet
from .base import EnvironmentFeedback, Environment


class StaticEnvironment(Environment):
    """
    Static environment that initializes everything from the dataframe
    and doesn't not require requesting feedback to create the ground truth.

    Attributes
        df (InternalDataFrame): The dataframe containing the ground truth.
        ground_truth_columns ([Dict[str, str]]):
            A dictionary mapping skill outputs to ground truth columns.
            If not specified, the skill outputs are assumed to be the ground truth columns.
            If a skill output is not in the dictionary, it is assumed to have no ground truth signal - NaNs are returned in the feedback.
        matching_function (str, optional): The matching function to match ground truth strings with prediction strings.
                                           Defaults to 'fuzzy'.
        matching_threshold (float, optional): The matching threshold for the matching function.

    Examples:
        >>> df = pd.DataFrame({'skill_1': ['a', 'b', 'c'], 'skill_2': ['d', 'e', 'f'], 'skill_3': ['g', 'h', 'i']})
        >>> env = StaticEnvironment(df, ground_truth_columns={'skill_1': 'ground_truth_1', 'skill_2': 'ground_truth_2'})
    """

    df: InternalDataFrame = None
    ground_truth_columns: Dict[str, str] = Field(default_factory=dict)
    matching_function: Union[str, Callable] = "fuzzy"
    matching_threshold: float = 0.9

    def get_feedback(
        self,
        skills: SkillSet,
        predictions: InternalDataFrame,
        num_feedbacks: Optional[int] = None,
    ) -> EnvironmentFeedback:
        """
        Compare the predictions with the ground truth using the specified matching function.

        Args:
            skills (SkillSet): The skill set being evaluated.
            predictions (InternalDataFrame): The predictions to compare with the ground truth.
            num_feedbacks (Optional[int], optional): The number of feedbacks to request. Defaults to all predictions

        Returns:
            EnvironmentFeedback: The resulting ground truth signal, with matches and errors detailed.

        Raises:
            NotImplementedError: If the matching_function is unknown.
        """

        pred_columns = list(skills.get_skill_outputs())
        pred_match = {}
        pred_feedback = {}

        if num_feedbacks is not None:
            predictions = predictions.sample(n=num_feedbacks)

        for pred_column in pred_columns:
            pred = predictions[pred_column]
            gt_column = self.ground_truth_columns.get(pred_column, pred_column)
            if gt_column not in self.df.columns:
                # if ground truth column is not in the dataframe, assume no ground truth signal - return NaNs
                pred_match[pred_column] = InternalSeries(np.nan, index=pred.index)
                pred_feedback[pred_column] = InternalSeries(np.nan, index=pred.index)
                continue

            gt = self.df[gt_column]

            gt, pred = gt.align(pred)
            nonnull_index = gt.notnull() & pred.notnull()
            gt = gt[nonnull_index]
            pred = pred[nonnull_index]
            # compare ground truth with predictions
            if isinstance(self.matching_function, str):
                if self.matching_function == "exact":
                    gt_pred_match = gt == pred
                elif self.matching_function == "fuzzy":
                    gt_pred_match = fuzzy_match(
                        gt, pred, threshold=self.matching_threshold
                    )
                else:
                    raise NotImplementedError(
                        f"Unknown matching function {self.matching_function}"
                    )
            elif callable(self.matching_function):
                gt_pred_match = gt.combine(
                    pred, lambda g, p: self.matching_function(g, p)
                )
            pred_match[pred_column] = gt_pred_match
            # leave feedback about mismatches
            match_concat = InternalDataFrameConcat(
                [gt_pred_match.rename("match"), gt], axis=1
            )
            pred_feedback[pred_column] = match_concat.apply(
                lambda row: "Prediction is correct."
                if row["match"]
                else f'Prediction is incorrect. Correct answer: "{row[gt_column]}"'
                if not pd.isna(row["match"])
                else np.nan,
                axis=1,
            )

        fb = EnvironmentFeedback(
            match=InternalDataFrame(pred_match).reindex(predictions.index),
            feedback=InternalDataFrame(pred_feedback).reindex(predictions.index),
        )
        return fb

    def get_data_batch(self, batch_size: int = None) -> InternalDataFrame:
        """
        Return the dataset containing the ground truth data.

        Returns:
            InternalDataFrame: The data batch.
        """
        if batch_size is not None:
            return self.df.sample(n=batch_size)
        return self.df

    def save(self):
        """
        Save the current state of the StaticEnvironment.
        """
        raise NotImplementedError("StaticEnvironment does not support save/restore.")

    def restore(self):
        """
        Restore the state of the StaticEnvironment.
        """
        raise NotImplementedError("StaticEnvironment does not support save/restore.")

