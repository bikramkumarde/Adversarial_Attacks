# Adversarial_Attacks
This repository contains the files and folders to run the project on Adversarial Attacks on time series and its corresponding modified code.

# Steps:

# Installation
1. Clone: Clone this repository using git clone
2. Installation: Run the requirements.txt file as present in the installation instructions. `pip install -r requirements.txt`
3. Download the dataset following the instructions.
4. Data can be obtained http://www.cs.ucr.edu/~eamonn/time_series_data/
5. Extract that into some folder and it will give 125 different folders. Copy-paste the util script `extract_all_datasets.py` (found inside `utils`) to this folder and run it to get a single folder `_data` with all 125 datasets extracted. Cut-paste these files into the root of the project and rename it as the `data` directory.
6. Run the unzip.ipynb to unzip the folder. It already contains the password required.
   
# Training and Evaluation
7. You need to run several scripts starting with training testing and evaluation.
8. White-box attack on Neural Network : `search_ts_nn_gatn_whitebox.py`, `eval_ts_nn_gatn_whitebox.py`, `vis_ts_nn_gatn_whitebox.py`.
9. To run CNN model: `search_ts_nn_gatn_whitebox.py`
10. To run LSTM model: `search_ts_nn_gatn_whitebox_new.py`
11. search script to train
12. eval script to test/evaluate
13. vis script to visualize particular sample of particular dataset

14. The following methodology is more practical when visualizing adversaries : 

- Run the viz script with the correct parameters once and `CLASS_ID = None`, `SAMPLE_ID = 0` and read the `Adversary List = [...]` printed. These are the sample ids that have been affected by adversarial attack.

- On the second run, select an id from thie `Adversary List` and set it as `SAMPLE_ID`.
-----





## Searching for Adversaries

This is the main script, used to create the adversarial sample generator. There are many parameters that may be edited.

- `datasets` : List of dataset ids corresponding to the ids on the UCR Archive.
- `target class`: Changing the target class may improve or harm the generation of adversaries.
- `alpha`: The weight of the target class inside the reranking function.
- `beta`: List of reconstruction weights. Increasing it gives fewer adversaries with reduced MSE. Increasing it gives more adversaries with heightened MSE.

The logs generated from this script contain some useful information, such as the number of adversaries generated per beta.


# Results
The results in the log files:
`gatn_nn_whitebox_results_cnn.csv`: For CNN training results
`gatn_nn_whitebox_results__test_cnn.csv`: For CNN testing results
`gatn_nn_whitebox_results_lstm.csv`: For LSTM training results
`gatn_nn_whitebox_results_lstm_test.csv`: For LSTM testing results

