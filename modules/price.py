import json
import urllib2
import urllib
import os
import traceback

import willie
from iron_cache import *
from bs4 import BeautifulSoup
import titlecase
import requests

from constants.mtgprice_api import set_symbols

def construct_name(name_input):
    """
    Construct a spaceless name for use with MTGPrice's API.
    """
    print("Constructing a name based on " + name_input)
    return titlecase.titlecase(name_input).replace(' ', '_')


def construct_set(set_input):
    """
    Construct a spaceless set name for use with MTGPrice's API.
    """
    print("Constructing a set based on " + set_input)
    if set_input.upper() in set_symbols:
        print("Found " + set_input + " in set_symbols, passing through.")
        return set_symbols[set_input.upper()]

    return titlecase.titlecase(set_input).replace(' ', '_')


def construct_id(name_input, set_input):
    """
    Construct the MTGPrice API ID for use with the cache.
    """
    name = construct_name(name_input)
    set_name = construct_set(set_input)

    print("Constructing an ID from " + name + " and " + set_name)
    return name + set_name + "falseNM-M"


def load_set(set_name):
    """
    Loads a set into the cache, only fired if the set_marker isn't already
    there. All cache items expire after a day.
    """
    print("Loading set: " + set_name)
    cache = IronCache()

    if set_name.upper() in set_symbols:
        set_name = set_symbols[set_name.upper()]
    print("Calling mtgprice API for set: " + set_name)
    response = requests.get('http://www.mtgprice.com/api?apiKey='+os.environ['MTGPRICEAPI']+'&s=' + set_name)
    data = None

    print("Loading JSON from MTGPrice for: " + set_name)
    data = response.json()

    print("Caching card list for: " + set_name)
    cards_list = data['cards']
    for card in cards_list:
        if "//" not in card['mtgpriceID']:
            cache.put(
                cache="mtgprice",
                key=card['mtgpriceID'],
                value=card['fairPrice'],
                options={"expires_in": 86400, "add": True}
            )
    print("Caching set marker for: " + set_name)
    msg = cache.put(
        cache="mtgprice",
        key=set_name,
        value="True",
        options={"expires_in": 86400, "add": True}
    )

    return True


def set_exists(set_name):
    """
    Checks if the set has been loaded into the cache. This is our way of knowing
    if a card really exists or if it's just not with us without looping forever.
    """
    print("Checking if set " + set_name + " exists in the cache.")
    cache = IronCache()

    try:
        if set_name.upper() in set_symbols:
            set_name = set_symbols[set_name.upper()]
        set_marker = cache.get(cache="mtgprice", key=set_name)
    except:
        set_marker = None

    if set_marker:
        print("Found cached set: " + set_name)
        return True
    else:
        print("Set not found in cache: " + set_name)
        return False


def get_card(name, set_name):
    """
    Gets a single card of the form card.value and card.key. Trys to get it out
    of the cache, and if that fails it trys to load the set.
    """
    cache = IronCache()
    card = None

    try:
        print("Getting card: " + name + " " + set_name)
        card = cache.get(cache="mtgprice", key=construct_id(name, set_name))
    except:
        print("Card not found in cache: " + name + " " + set_name)
        card = None
    if not card:
        if set_exists(construct_set(set_name)):
            print("Card " + name + " " + set_name + " doesn't exist, set is cached.")
            return None
        else:
            print("Set " + set_name + " wasn't found, caching and trying again.")
            load_set(construct_set(set_name))
            card = get_card(name, set_name)

    return card


def get_deckbrew(input_name, input_set=None):
    """
    To be used when the cache and mtgprice have failed. This should let us do
    some fuzzy name only matches.
    """
    data = requests.get('http://api.deckbrew.com/mtg/cards?'+urllib.urlencode({'name': input_name})).json()
    card = None
    set_ret = None
    name_ret = None

    print("Attempting to get card from deckbrew. ATTN: Broken.")
    if len(data) > 0:
        data = data[0]
        fuzzy_name = data['name']
        editions = data['editions']

        if input_set:
            for item in editions:
                if item['set'].lower() == input_set.lower():
                    card = get_card(construct_name(fuzzy_name), construct_set(input_set))
                    set_ret = item['set']
                    name_ret = fuzzy_name

        if not card:
            card = get_card(construct_name(fuzzy_name), construct_set(editions[0]['set']))
            set_ret = editions[0]['set']
            name_ret = fuzzy_name

    return card, name_ret, set_ret


@willie.module.commands('price')
def price(bot, trigger):
    """
    Grab the price for the given card (and optional set). Information can come
    from any API that outputs JSON.
    """
    try:
        card = None
        options = trigger.group(2).split(' !')
        options = [x.encode('utf-8').rstrip() for x in options]
        if len(options) > 1:
            print("Name and set passed in, try getting them directly.")
            name = options[0]
            set_name = options[1]
            card = get_card(name, set_name)
            if card:
                print("Found card in cache/MTGPrice, replying.")
                bot.reply(titlecase.titlecase(options[0]) + ' | MTGPrice.com fair price: ' + card.value + ' | Set: ' + construct_set(set_name).replace('_', ' '))
            else:
                print("Card not found in cache/MTGPrice, trying deckbrew.")
                card, fuzzy_name, fuzzy_set = get_deckbrew(options[0], options[1])
                if card:
                    bot.reply(fuzzy_name + ' | MTGPrice.com fair price: ' + card.value + ' | Set: ' + fuzzy_set)
                else:
                    bot.reply("No results.")

        elif options[0]:
            print("Only card name given: " + options[0] + " attempting to fuzzy match set.")
            card, fuzzy_name, fuzzy_set = get_deckbrew(options[0])
            if card:
                print("Successfully matched, replying with card information.")
                bot.reply(fuzzy_name + ' | MTGPrice.com fair price: ' + card.value + ' | Set: ' + fuzzy_set)
            else:
                print("Failed to fuzzy find match, replying with no results.")
                bot.reply("No results.")

        else:
            print("No searching techniques worked, replying with failure.")
            bot.reply("No results.")

    except Exception as e:
        traceback.print_exc()
        print("Exception while searching: ")
        bot.reply("No results (or you broke me).")


@willie.module.commands('define')
def define(bot, trigger):
    """
    Get the definition for the given keyword or rule. The given keyword needs
    to be an id on yawgatog.com for this to work correctly. Right now it's
    scraping in the future it should hit an API.
    """
    try:
        option = trigger.group(2)
        option = option.encode('utf-8').rstrip()
        data = urllib2.urlopen('http://www.yawgatog.com/resources/magic-rules/')
        soup = BeautifulSoup(data)
        anchor_tag = soup.find('a', id=option)
        reply = anchor_tag.string
        for sibling in anchor_tag.next_siblings:
            if sibling.string:
                reply = reply + ' ' + sibling.string
        bot.reply(reply)

    except Exception as e:
        print(e)
        bot.reply("No results (or you broke me).")


@willie.module.commands('formats')
def formats(bot, trigger):
    """
    Respond to the user with the format information for a given card.
    """
    try:
        option = trigger.group(2)
        option = option.encode('utf-8').rstrip()
        data = requests.get('http://api.deckbrew.com/mtg/cards?'+urllib.urlencode({'name': option})).json()
        if len(data) > 0:
            data = data[0]
            name = data['name']
            formats = data['formats']
            output = name + " is "
            for key in formats:
                legality = formats[key]
                if legality == "legal":
                    output = output + "legal in " + key.capitalize() + ", "
                if legality == "restricted":
                    output = output + "legal in " + key.capitalize() + ", "
            out_sections = output.rsplit(",", 1)[0].rsplit(",", 1)
            if len(out_sections) == 1:
                output = out_sections[0] + "."
            else:
                output = out_sections[0] + ", and" + out_sections[1] + "."
            bot.reply(output)
        else:
            bot.reply("No results.")
    except Exception as e:
        print(e)
        bot.reply("No results (or you broke me).")
