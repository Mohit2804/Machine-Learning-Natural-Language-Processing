import os

# Install java
! apt-get install -y openjdk-8-jdk-headless -qq > /dev/null
os.environ["JAVA_HOME"] = "/usr/lib/jvm/java-8-openjdk-amd64"
os.environ["PATH"] = os.environ["JAVA_HOME"] + "/bin:" + os.environ["PATH"]
! java -version

# Install pyspark
! pip install --ignore-installed pyspark==2.4.5

# Install Spark NLP
! pip install --ignore-installed spark-nlp==2.4.5

# Install nltk
! pip install nltk

import sparknlp

spark = sparknlp.start()

from pyspark.sql import functions as F
data_path = 'sample_data/Musical_instruments_reviews.csv'
data = spark.read.csv(data_path, header=True)

data.columns

text_col = 'reviewText'
review_text = data.select(text_col).filter(F.col(text_col).isNotNull())

review_text.limit(5).show(truncate=90)

from sparknlp.base import DocumentAssembler

documentAssembler = DocumentAssembler() \
     .setInputCol(text_col) \
     .setOutputCol('document')

from sparknlp.annotator import Tokenizer

tokenizer = Tokenizer() \
     .setInputCols(['document']) \
     .setOutputCol('tokenized')

from sparknlp.annotator import Normalizer

normalizer = Normalizer() \
     .setInputCols(['tokenized']) \
     .setOutputCol('normalized') \
     .setLowercase(True)

from sparknlp.annotator import LemmatizerModel

lemmatizer = LemmatizerModel.pretrained() \
     .setInputCols(['normalized']) \
     .setOutputCol('lemmatized')

import nltk
nltk.download('stopwords')

from nltk.corpus import stopwords

eng_stopwords = stopwords.words('english')

from sparknlp.annotator import StopWordsCleaner

stopwords_cleaner = StopWordsCleaner() \
     .setInputCols(['lemmatized']) \
     .setOutputCol('unigrams') \
     .setStopWords(eng_stopwords)

from sparknlp.annotator import NGramGenerator

ngrammer = NGramGenerator() \
    .setInputCols(['lemmatized']) \
    .setOutputCol('ngrams') \
    .setN(3) \
    .setEnableCumulative(True) \
    .setDelimiter('_')

from sparknlp.annotator import PerceptronModel

pos_tagger = PerceptronModel.pretrained('pos_anc') \
    .setInputCols(['document', 'lemmatized']) \
    .setOutputCol('pos')

from sparknlp.base import Finisher

finisher = Finisher() \
     .setInputCols(['unigrams', 'ngrams', 'pos']) \

from pyspark.ml import Pipeline

pipeline = Pipeline() \
     .setStages([documentAssembler,                  
                 tokenizer,
                 normalizer,                  
                 lemmatizer,                  
                 stopwords_cleaner, 
                 pos_tagger,
                 ngrammer,  
                 finisher])

processed_review = pipeline.fit(review_text).transform(review_text)

processed_review.limit(5).show()

from pyspark.sql import types as T

udf_join_arr = F.udf(lambda x: ' '.join(x), T.StringType())
processed_review  = processed_review.withColumn('finished_pos', udf_join_arr(F.col('finished_pos')))

pos_documentAssembler = DocumentAssembler() \
     .setInputCol('finished_pos') \
     .setOutputCol('pos_document')

pos_tokenizer = Tokenizer() \
     .setInputCols(['pos_document']) \
     .setOutputCol('pos')

pos_ngrammer = NGramGenerator() \
    .setInputCols(['pos']) \
    .setOutputCol('pos_ngrams') \
    .setN(3) \
    .setEnableCumulative(True) \
    .setDelimiter('_')

pos_finisher = Finisher() \
     .setInputCols(['pos', 'pos_ngrams']) \

pos_pipeline = Pipeline() \
     .setStages([pos_documentAssembler,                  
                 pos_tokenizer,
                 pos_ngrammer,  
                 pos_finisher])

processed_review = pos_pipeline.fit(processed_review).transform(processed_review)

processed_review.columns

processed_review.select('finished_ngrams', 'finished_pos_ngrams').limit(5).show()

def filter_pos(words, pos_tags):
    return [word for word, pos in zip(words, pos_tags) 
            if pos in ['JJ', 'NN', 'NNS', 'VB', 'VBP']]

udf_filter_pos = F.udf(filter_pos, T.ArrayType(T.StringType()))

processed_review = processed_review.withColumn('filtered_unigrams',
                                               udf_filter_pos(F.col('finished_unigrams'), 
                                                              F.col('finished_pos')))

processed_review.select('filtered_unigrams').limit(5).show(truncate=90)

def filter_pos_combs(words, pos_tags):
    return [word for word, pos in zip(words, pos_tags) 
            if (len(pos.split('_')) == 2 and \
                pos.split('_')[0] in ['JJ', 'NN', 'NNS', 'VB', 'VBP'] and \
                 pos.split('_')[1] in ['JJ', 'NN', 'NNS']) \
            or (len(pos.split('_')) == 3 and \
                pos.split('_')[0] in ['JJ', 'NN', 'NNS', 'VB', 'VBP'] and \
                 pos.split('_')[1] in ['JJ', 'NN', 'NNS', 'VB', 'VBP'] and \
                  pos.split('_')[2] in ['NN', 'NNS'])]
    
udf_filter_pos_combs = F.udf(filter_pos_combs, T.ArrayType(T.StringType()))

processed_review = processed_review.withColumn('filtered_ngrams',
                                               udf_filter_pos_combs(F.col('finished_ngrams'),
                                                                    F.col('finished_pos_ngrams')))

processed_review.select('filtered_ngrams').limit(5).show(truncate=90)

from pyspark.sql.functions import concat
processed_review = processed_review.withColumn('final', 
                                               concat(F.col('filtered_unigrams'), 
                                                      F.col('filtered_ngrams')))

processed_review.select('final').limit(5).show(truncate=90)

from pyspark.ml.feature import CountVectorizer

tfizer = CountVectorizer(inputCol='final', outputCol='tf_features')
tf_model = tfizer.fit(processed_review)
tf_result = tf_model.transform(processed_review)

from pyspark.ml.feature import IDF

idfizer = IDF(inputCol='tf_features', outputCol='tf_idf_features')
idf_model = idfizer.fit(tf_result)
tfidf_result = idf_model.transform(tf_result)

from pyspark.ml.clustering import LDA

num_topics = 6
max_iter = 10

lda = LDA(k=num_topics, maxIter=max_iter, featuresCol='tf_idf_features')
lda_model = lda.fit(tfidf_result)

vocab = tf_model.vocabulary

def get_words(token_list):
     return [vocab[token_id] for token_id in token_list]
       
udf_to_words = F.udf(get_words, T.ArrayType(T.StringType()))

num_top_words = 10

topics = lda_model.describeTopics(num_top_words).withColumn('topicWords', udf_to_words(F.col('termIndices')))
topics.select('topic', 'topicWords').show(truncate=90)
