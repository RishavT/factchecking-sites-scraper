## Scraper Functions for Boomlive
## 16 Feb 2021

from time import time, sleep
from datetime import date, datetime
from dateutil.parser import parse
from pyquery import PyQuery
import pytz
import json  #TODO: Discuss pickle vs json ; Decided JSON
from bson import json_util
from PIL import Image
from io import BytesIO
from tqdm import tqdm
from numpy.random import randint
import uuid

from pymongo import MongoClient
from pymongo.collection import Collection

from selenium import webdriver
from lxml.html import fromstring
import requests

import os
from dotenv import load_dotenv
load_dotenv()

## Decided: For Constants generate config file. Avoid domain specific functions in common config. 

MONGOURL = os.environ["SCRAPING_URL_REMOTE"] 
DB_NAME = os.environ["DB_NAME"]
COLL_NAME = os.environ["COLL_NAME"]

DB_NAME = "factcheck_sites_dev"
COLL_NAME = "stories"
CRAWL_PAGE_COUNT = 1
headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_11_5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/50.0.2661.102 Safari/537.36",
        "Content-Type": "text/html",
    }

# ============================== GET COLLECTION  ===========================

def get_collection(MONGOURL, DB_NAME, COLL_NAME):
    cli = MongoClient(MONGOURL)
    db = cli[DB_NAME]
    collection = db[COLL_NAME]

    return collection

# ===========================================================================   


# ============================== BEGIN AWS CONNECTION  =========================== 
def aws_connection(self):
    """
    Get AWS connection

    Returns:

    """
    access_id = os.environ["ACCESS_ID"]
    access_key = os.environ["ACCESS_KEY"]

    s3 = boto3.client(
        "s3",
        region_name="ap-south-1",
        aws_access_key_id=access_id,
        aws_secret_access_key=access_key,
    )

    return s3

# ===============================================================================


# ============================== GET TREE  ===========================   

def get_tree(url: str):
    # get the tree of each page
    # TODO: https://www.peterbe.com/plog/best-practice-with-retries-with-requests
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_11_5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/50.0.2661.102 Safari/537.36",
        "Content-Type": "text/html",
    }
    html = None
    for _ in range(3):
        try:
            html = requests.get(url, headers=headers)
            break
        except Exception as e:
            print(f"failed request: {e}")
            sleep(randint(5,10))
    
            html.encoding = "utf-8"

    tree = fromstring(html.text)

    return tree

# ==============================================================================

# ================================ RETURN UNICODE  =============================
def restore_unicode(mangled):
    return mangled.encode('utf8').decode('utf8')

# ==============================================================================


# ============================= CRAWLER BEGIN ========================    

def crawler(crawl_url, page_count) -> list: 
    """
    get story links based on url and page range
    extract all URLs in pages, discard URLs already in collection
    """
    print("entered crawler")
    url_list = []

    coll = get_collection(MONGOURL, DB_NAME, COLL_NAME)

    for page in tqdm(range(CRAWL_PAGE_COUNT), desc="pages: "):
        

        page_url = f"{crawl_url}/{page}"
        tree = get_tree(page_url)   

        permalinks = PyQuery(tree).find(".entry-title>a")
        
        for pl in permalinks:
            link = crawl_url + pl.attrib['href']
            if coll.count_documents({"postURL": link}, {}):
                print(link, "exists in collection")
                continue
                    
            # TODO: Remove this line to stop scraping on encountering older articles
            else:
                url_list.append(link)
        sleep(randint(5,10))
    
        # TODO: crawl till a specific date 

      

    # get unique urls
    url_list = list(set(url_list))
    with open("url_list.json", 'w') as f:
        json.dump(url_list,f)
    return url_list

# ============================================================================== 


# ============================= ARTICLE DOWNLOADER BEGIN =======================
def article_downloader(url): 
    print("entered downloader")
    print(url)
    
    # time_millis = int(time() * 1000)
    file_name = f'/tmp/scraper_files/{url.split("/")[-2]}.html'

    if os.path.exists(file_name):
        with open(file_name) as f:
            html_text = f.read()
    else:
        response = requests.get(url, headers=headers)
        html_text = response.text
        with open(file_name, "w") as f:
            f.write(html_text)
    
    return html_text

    # response = requests.get(url, headers=headers)

    # with open(file_name, "w") as f:
    #     f.write(response.text)
    
    # with open("url_link.text","w") as f:
    #     f.write(url)

    # return response

# ==============================================================================


# ============================= PARSER BEGIN =======================

def get_article_info(pq):
    headline = pq("h1.entry-title").text()
    #import ipdb; ipdb.set_trace()
    datestr = pq('span.date>span').text().split('Updated')[0]
    datestr = parse(datestr).astimezone(pytz.timezone('Asia/Calcutta')).strftime("%B %d, %Y")
    author_name = pq('a.author-name').text()
    author_link = pq('a.author-name').attr['href']
    article_info = {
        "headline": restore_unicode(headline),
        "author": restore_unicode(author_name),
        "author_link": restore_unicode(author_link),
        "date_updated": restore_unicode(datestr),
    }
    return article_info

def get_article_content(pq):
    
    content = {
        "text": [],
        "video": [],
        "image": [],
        "tweet": [],
        "facebook": [],
        "instagram": [],
    }

    ## text content
    content['text'] = restore_unicode(pq('div.story').text())
    
    ## images
    images = pq.find('figure>img')
    images += pq.find('.image-and-caption-wrapper>img')
    images += pq.find('.single-featured-thumb-container>img')

    for i in images:
        if 'src' in i.attrib:
            content["image"].append(i.attrib["src"])

    ## video embed
    video_embed = pq.find("video>source")
    for v in video_embed:
        content["video"].append(v.attrib["src"])
    
    video_yt = pq.find('iframe')  # video youtube
   
    for v in video_yt:
        if 'lazy' in v.attrib.get('class', ''):
            continue
        content["video"].append(v.attrib["src"])
   
    fb = pq.find('.wp-block-embed-facebook>.fb-video')   # video fb
    for f in fb:
        content["facebook"].append(f.attrib["data-href"])

    # fb = tree.xpath('//figure[contains(@class, "wp-block-embed")]//a')
    # TODO: video_fb = tree.xpath('//figure[contains(@class, "wp-block-embed")]//a')

   
    # # tweet
    # tweets = tree.xpath('//blockquote[@class="twitter-tweet"]//a')
    # for t in tweets:
    #     if t.text and any(m in t.text for m in months):
    #         content["tweet"].append(t.get("href"))

    # # instagram
    # insta = tree.xpath(
    #     '//figure[contains(@class, "wp-block-embed-instagram")]//blockquote'
    # )
    # for i in insta:
    #     content["instagram"].append(i.get("data-instgrm-permalink"))

    # for i, x in enumerate(body_elements):
    #     text_content = x.text_content()
    #     if text_content:
    #         content["text"].append(text_content)

    
    # for p in pq.find('p'):
    #     text = p.text
    #     if text:
    #         content['text'].append(text)

    return content

def article_parser(html_text, story_url, domain, langs):
    
    print("entered parser")
    pq = PyQuery(html_text)
    
    # generate post_id
    post_id = uuid.uuid4().hex

    article_info = get_article_info(pq)

    # uniform date format
    now_date = date.today().strftime("%B %d, %Y")
    now_date_utc = datetime.utcnow()
    date_updated = article_info["date_updated"]
    date_updated_utc = datetime.strptime(date_updated, "%B %d, %Y")

    author = {"name": article_info["author"], "link": article_info["author_link"]}  

    langs = None #TODO: Discuss    (This should be defined in constants section within file)
    

    article_content = get_article_content(pq)
    docs = []
    for k, v in article_content.items():
        if not v:  # empty list
            continue
        
        doc_id = uuid.uuid4().hex
        
        if k == "text":  
            doc = {
                "doc_id": doc_id,
                "postID": post_id,
                "domain": domain,
                "origURL": story_url, # for text content, URL is the URL of the story
                "s3URL": None,
                "possibleLangs": langs,
                "mediaType": k,
                "content": v,  # text, if media_type = text or text in image/audio/video
                "nowDate": now_date,  # date of scraping, same as date_accessed
                "nowDate_UTC": now_date_utc,
                "isGoodPrior": None,  # no of [-ve votes, +ve votes] TODO: Discuss  Discussed: Look More
            }
            docs.append(doc)
        
        else:
            for url in v:
                doc = {
                    "doc_id": doc_id,
                    "postID": post_id,
                    "domain": domain,
                    "origURL": url,  # for images,videos URL is the URL of the media item.
                    "s3URL": None,
                    "possibleLangs": langs,
                    "mediaType": k,
                    "content": None,  # this field is specifically to store text content.
                    "nowDate": now_date,  # date of scraping, same as date_accessed
                    "nowDate_UTC": now_date_utc,
                    "isGoodPrior": None,  # no of [-ve votes, +ve votes] TODO: Discuss
                }  
                docs.append(doc)          

    post = {
        "postID": post_id,  # unique post ID
        "postURL": story_url,  
        "domain": domain,  # domain such as altnews/factly
        "headline": article_info["headline"],  # headline text
        "date_accessed": now_date,  # date scraped
        "date_accessed_UTC": now_date_utc,
        "date_updated": date_updated,  # later of date published/updated
        "date_updated_UTC": date_updated_utc,  # later of date published/updated
        "author": author,
        "s3URL": None,
        "post_category": None,
        "claims_review": None,
        "docs": docs,
    }

    print(post)


    time_millis = int(time() * 1000)
    file_name = f'{time_millis}_{url.split("/")[-2]}.json'
    json_data = json.dumps(post,  default=convert_timestamp)
    with open(file_name, 'w') as f:
        f.write(json_data)
    
    return post 

def convert_timestamp(item_date_object):
    if isinstance(item_date_object, (date, datetime)):
        return item_date_object.timestamp()

# ==============================================================================


# ============================= EMBED DOWNLOADER BEGIN =======================
def get_all_images(post):
    # get all image docs
    # get a list of urls and postIDs

    url = None
    filename_dict = {}  # dictionary to link doc_id to locally saved filename

    for doc in post["docs"]:
        if (doc["mediaType"] == 'image'):
            url = doc["origURL"]
            if url is None:
                print("Media url is None. Setting s3URL as error...")
                doc["s3_url"] = "ERR"
            else:
                if url.endswith("://"):
                    # handle valid filename eg https://i0.wp.com/www.altnews.in/wp-content/uploads/2017/04/electrification-percentages.jpg?resize=696%2C141http://
                    filename = url.split("/")[-3] + "//"
                else:
                    filename = url.split("/")[-1]
                if "?" in filename:
                    filename = filename.split("?")[0]

                if filename == "RDESController":
                    # handle files served by boomlive servlet
                    # eg - https://bangla.boomlive.in/content/servlet/RDESController?command=rdm.Picture&app=rdes&partner=boomlivebn&type=7&sessionId=RDWEBCM4UOT387MUCCO9K206WYURB7TIJPR0S&uid=5780889mysxCnqsjTKn5C4C0mXDHoqhwayM7B9087027
                    url_split = url.split("uid=")
                    filename = url_split[1]

                r = requests.get(url, headers=headers)
                image = Image.open(BytesIO(r.content)) 
                if len(filename.split(".")) == 1:
                        # TODO: handle possible filename without extensions
                        #   - some filenames contain '.' apart from extension
                        #   eg WhatsApp-Image-2018-07-24-at-10.39.25-AM.jpeg
                        filename = f"{filename}.{image.format.lower()}"
                
                image.save(filename)
                #filename_dict[doc["doc_id"]] = filename   #TODO: what is correct syntax
                filename_dict.update({doc["doc_id"]: filename})
                
    return filename_dict

def media_downloader(post):
    print("entered media downloader")
    media_dict = get_all_images(post)
    return media_dict

# ============================================================================== 


# ============================= DATA UPLOADER BEGIN =======================
def data_uploader(post,media_dict,html_text):

    print("entered data uploader")

    coll = get_collection(MONGOURL, DB_NAME, COLL_NAME)
    s3 = aws_connection()



    for doc in post["docs"]:
            filename = media_dict.get(doc["doc_id"])
            if (filename != None):
                s3_url = f"https://{BUCKET}.s3.{REGION_NAME}.amazonaws.com/{filename}" #upload media file to s3
                doc.update("s3URL",s3_url)
            else:
                continue
    
    coll.insert_one(post)

    ### write html to s3
    with open(file_name, 'w') as f:
        f.write(html)

# ==============================================================================

# ============================= MAIN FUNCTION =======================

def main():
    print('boomlive scraper initiated')
    boom_sites = {
    "boomlive.in": {
        "url": "https://www.boomlive.in/fact-check",
        "langs": ["english"],
        "domain": "boomlive.in",
    },
    "hindi.boomlive.in": {
        "url": "https://hindi.boomlive.in/fact-check",
        "langs": ["hindi"],
        "domain": "hindi.boomlive.in",
    },
    "bangla.boomlive.in": {
        "url": "https://bangla.boomlive.in/fact-check",
        "langs": ["bengali"],
        "domain": "bangla.boomlive.in",
    },
    
    CRAWL_PAGE_COUNT = 2


    for site in boom_sites:
        print(site["domain"])
        links = crawler("url,CRAWL_PAGE_COUNT)

        print(links)

        for link in links:
            html_response = article_downloader(link)
            post = article_parser(html_response,link,site["domain"],site["lang"])
            media_items = media_downloader(post)
            data_uploader(post,media_items,html)
            # if (DEBUG==0):
            # delete post, medi_items but not html_response

if __name__ == "__main__":
    main()