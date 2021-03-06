import json
from copy import deepcopy, copy

import numpy as np
import re

DEBUG = False

if DEBUG:
    import matplotlib.pyplot as plt
    plt.style.use('seaborn-whitegrid')

    
WINDOW = 200
MIN_RAMP_LEN = 3
MIN_ANCHOR_LEN = 8
    
def _show(datas, n=1):
    global fig_count
    fig_count+=1
    fig = plt.figure(fig_count)
    x = [n[0] for n in datas]
    y = [n[1] for n in datas]
    plt.scatter(y,x)

def filter_non_sense(inp, threshold=10000):
    return [v for v in inp if (v[0]>0 and v[0]<threshold)]
    
def filter_ref(inp, text):
    return [v for v in inp if (text[v[1]] not in ["(",'['])]
    
def filter_has_neighbors(inp):
    nb_set = list(set([n[0] for n in inp]))
    nb_set.sort()

    fnb_set = []
    for i in range(1, len(nb_set)-1 ):
        if nb_set[i-1]==nb_set[i]-1:
            fnb_set.append(nb_set[i])
            fnb_set.append(nb_set[i-1])
        if nb_set[i+1]==nb_set[i]+1:
            fnb_set.append(nb_set[i])
            fnb_set.append(nb_set[i+1])
    fnb_set = list(set(fnb_set))
    fnb_set.sort()

    filtered_numbers = [v for v in inp if v[0] in fnb_set]
    filtered_numbers.sort(key=lambda x : x[1])

    del fnb_set

    return filtered_numbers

def get_elements_in_window(inp, fro, to):
        ret=[]
        for n in inp:
            if n[1]<fro-1:
                continue
            elif n[1]>to+1:
                break
            else:
                ret.append(n)
        return ret

def check_previous_value(inp, at, window = WINDOW):
        if at<0 or at>=len(inp):
            return False
        n, a = inp[at]
        return (n-1) in [ni[0] for ni in get_elements_in_window(inp, a-window, a)]

def check_next_value(inp, at, window = WINDOW):
        if at<0 or at>=len(inp):
            return False
        n, a = inp[at]
        return (n+1) in [ni[0] for ni in get_elements_in_window(inp, a, a+window)]

def get_next(inp, at, window = WINDOW):
        if at<0 or at>=len(inp):
            return False
        n, a = inp[at]
        for ic,nc in enumerate(get_elements_in_window(inp, a, a+window)):
            if nc[0]==n+1:
                return ic+at, nc
        return None, None

def get_ramps(inp, incremental_remove=False):
    #find ramps (DIRTY!)
    ramps = []
    tmp=inp#deepcopy(inp)
    used_list = []
    for i, n in enumerate(inp):
        if i in used_list:
            continue
        val = n[0]
        
            
        if check_next_value(inp, i):
            inext, nnext = get_next(inp, i)
            current_ramp = [n, nnext]
            used_list.append(i)
            used_list.append(inext)
            to_find = nnext[0]+1
            max_addr = nnext[1]+WINDOW
            
            start = inext
            done=False
            counter = 0
            
            while not done:
                counter+=1
                if counter>100000:
                    break
                if check_next_value(inp, start+counter):
                    inext, nnext = get_next(inp, start+counter)
                    current_ramp.append(nnext)
                    used_list.append(inext)
                    start = inext
                else:
                    break
            ramps.append(current_ramp)
            del current_ramp
            current_ramp = []

    #del tmp

    #filter by ramp length
    filtered_ramps = [r for r in ramps if len(r)>MIN_RAMP_LEN]
    #del ramps

    if len(filtered_ramps)>0 and incremental_remove:
        #incremental remove
        tmp = [r for r in filtered_ramps if len(r)>MIN_ANCHOR_LEN]
        if len(tmp)>0:
            tmp.sort(key = lambda x:x[0][0])
            #print(tmp)
            threshold = tmp[0][0][0]

            filtered_ramps_2 = []
            for r in filtered_ramps:
                if len(r)==0:
                    continue
                keep_ramp = True
                current_ramp=[]
                for n in r:
                    if n[0]>threshold:
                        current_ramp.append(n)
                if len(current_ramp)>0:
                    threshold = current_ramp[-1][0]
                    filtered_ramps_2.append(current_ramp)
        else:
            filtered_ramps_2 = []
    else:
        filtered_ramps_2 = filtered_ramps
    
    del filtered_ramps

    return filtered_ramps_2


def filter_lines_count(text_to_filter):
    text_to_filter = deepcopy(text_to_filter)
    try:
        if len(text_to_filter)==0:
            return ''
        #Extract integers and theres address
        str_values = re.findall("\d+", text_to_filter)

        offset = 0
        addr = []
        for v in str_values:
            addr.append( len(text_to_filter[offset:].split(v)[0]) +offset-1)
            offset = addr[-1]
        all_numbers = [ (int(v), a) for v, a in zip(str_values, addr)]

        if DEBUG:
            _show(all_numbers,1)

        # filter nonsense numbers
        filtered_numbers = filter_non_sense(all_numbers)

        if DEBUG:
            _show(filtered_numbers,2)

        # filter references
        filtered_numbers = filter_ref(filtered_numbers, text_to_filter)

        if DEBUG:
            _show(filtered_numbers,3)

        #filter by continous neighbors
        filtered_numbers = filter_has_neighbors(filtered_numbers)

        if DEBUG:
            _show(filtered_numbers,4)

        if len(filtered_numbers)==0:
            return text_to_filter
        #filter ramps
        filtered_numbers.sort(key=lambda x : x[1])
        ramps = get_ramps(filtered_numbers)
        

        ramps_sum= []
        for r in ramps:
            ramps_sum+=r
        ramps_sum.sort(key=lambda x : x[1])

        if DEBUG:
            _show(ramps_sum,5)

        #clean text
        if len(ramps_sum)>=2:
            to_clean = list(set(ramps_sum))
            to_clean.sort(key=lambda x : x[1])
        else:
            to_clean = []



        offset = 1

        rm_count = 0
        clean_text = list(copy(text_to_filter))
        #print('==>', len(clean_text))
        for torm in to_clean[::-1]:
            nlen = len(str(torm[0]))
            plen = len(clean_text)
            #print(torm, nlen)
            for i in range(nlen):
                clean_text.pop(torm[1]+offset)
            #clean_text = clean_text[:torm[1]-rm_count+offset] + clean_text[torm[1]-rm_count+nlen+offset:]
            rm_count+=nlen
            assert plen - len(clean_text) == nlen, "Assert on %s"%torm

        #remove double spaces
        clean_addrs = []
        for i in range(len(clean_text)-1):
            if clean_text[i] == clean_text[i+1] and clean_text[i]==' ':
                clean_addrs.append(i)

        for i in clean_addrs[::-1]:
            clean_text = clean_text[:i]+clean_text[i+1:]
        ret = ''.join(clean_text)
        #print(len(clean_text))
        #del filtered_numbers
        #del ramps
        #del ramps_sum
        #del to_clean
        #del clean_text
        #del clean_addrs
        
        
    except Exception as e:
        print('ERROR:', e, text_to_filter)
        ret= text_to_filter
        raise e
    return ret