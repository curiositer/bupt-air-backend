import random
import time
import mysql.connector

import json
from os import path

from flask import Blueprint, request, Response, jsonify
from concurrent.futures import ThreadPoolExecutor

f = open(path.join(path.dirname(path.dirname(__file__)), 'config.json'), 'r')
config = json.load(f)
f.close()


class mainMachine:
    main_status = 1  # 表示主机状态，制冷1、制热2
    is_standby = 1     # 记录是否待机，待机1、运行0
    num = 3  # 每秒最多处理请求数目，默认为3条
    n = 3  # 这一秒内还能接收n条请求
    choice = 1  # 调度算法选择，随机1、先来先服务2、风速优先3

    requestList = []  # 这一秒的请求列表
    responseList = []  # 这一秒要处理的请求列表
    flag = True

    def run(self):
        self.clear_request()
        while self.flag:
            self.db = mysql.connector.connect(**config)
            print('standby status ', self.is_standby)
            self.judge_status()
            if self.is_standby == 0:    # 若为运行状态，则进行请求处理
                self.n = self.num  # 初始化参数
                self.responseList = []  # 初始化
                self.requestList = []  # 初始化请求列表
                self.get_request()
            time.sleep(5)
            self.db.close()

    def exit(self):
        self.flag = False
        try:
            self.db.close()
        except AttributeError:
            pass

    def clear_request(self):    # 开机清空请求
        self.db = mysql.connector.connect(**config)
        cursor = self.db.cursor()
        delete_query = 'delete from request'
        cursor.execute(delete_query)
        self.db.commit()
        print('open the machine, and delete all requests')
        self.db.close()

    def set_status(self, status):  # 设置主机状态
        self.main_status = status
        cursor = self.db.cursor()
        query = 'SELECT id,target_temp FROM status '  # 执行该语句判断有无正在送风的从机
        cursor.execute(query)
        statusList = cursor.fetchall()
        if self.main_status == 1:
            for each in statusList:
                if each[1] > 25:    # 制冷模式，设定温度大于25度时
                    update_query = ('update status set target_temp=22 where id=%s'%each[0])
                    cursor.execute(update_query)
                    self.db.commit()  # 更新status表
        if self.main_status == 2:
            for each in statusList:
                if each[1] < 25:    # 供暖模式，设定温度小于25度时
                    update_query = ('update status set target_temp=28 where id=%s'%each[0])
                    cursor.execute(update_query)
                    self.db.commit()  # 更新status表

    def set_number_request(self, number):  # 设置每秒处理的请求数目
        self.num = number

    def set_schedule(self, choice):  # 设置调度类型
        self.choice = choice

    def judge_status(self):
        cursor = self.db.cursor()
        statusList = []
        if_request = []
        if self.is_standby == 0:
            query = 'SELECT * FROM `status` where speed<>0 '  # 执行该语句判断有无正在送风的从机
            cursor.execute(query)
            statusList = cursor.fetchall()
            print('status list are ', statusList)
            if statusList == []:  # 从机状态均为关机，主机进行待机操作
                # self.past_status = self.is_standby
                self.is_standby = 1
                print('no request，set to standby')
        if self.is_standby == 1:
            query2 = 'select * from request limit 1'    # 查询是否有请求
            cursor.execute(query2)
            if_request = cursor.fetchall()
            print('if_request list ', if_request)

            if if_request != []:    # 存在请求，则将主机状态改为待机前的状态
                self.is_standby = 0
                print('change back to last status')

    def get_request(self):
        print('get request and act')
        cursor = self.db.cursor()
        query = ('SELECT count(*) FROM `request` ')  # 执行该语句判断是否有请求及是否需要调度
        cursor.execute(query)
        requestCount = cursor.fetchall()
        n_request = requestCount[0][0]
        print('get request number is ', n_request)
        if n_request > 0:  # 有未响应请求
            query2 = ('SELECT * FROM `request`')
            cursor.execute(query2)
            self.requestList = cursor.fetchall()
            cursor.close()
            print('when first get request,it is', self.requestList)
            if n_request > self.num:  # 同一时间有大于num条请求
                self.choose_sort()
            else:
                self.response_request(self.requestList)

    def choose_sort(self):
        self.power_first()
        # print(self.responseList)
        if len(self.responseList) < 3:
            if (self.choice == 1):  # 随机
                self.random_sort()
            elif (self.choice == 2):  # 先来先服务
                self.first_sort()
            elif (self.choice == 3):  # 按风速大小优先
                self.speed_sort()

    def power_first(self):
        i = 0
        for each in self.requestList:  # 找出关机请求
            if i >= self.num:
                break
            if each[2] == 0:
                self.responseList.append(each)
                i = i + 1
                self.n = self.n - 1

        cursor = self.db.cursor()
        query = ('select id,speed from status where speed=0')
        cursor.execute(query)
        statusList = cursor.fetchall()

        for status in statusList:  # 找出开机请求
            if i >= self.num:
                break
            for req in self.requestList:
                if req[1] == status[0] and status[1] == 0 and req[2] != 0:
                    self.responseList.append(req)
                    i = i + 1
                    self.n = self.n - 1

        for req in self.responseList:  # 将相应请求在请求列表中删除
            if req in self.requestList:
                self.requestList.remove(req)

        print('after add response,questlist are:',self.requestList)

        if i >= self.num:  # 若开关机请求大于num，则直接接受请求
            self.response_request(self.responseList)
            self.responseList = []      # 这一秒内开关机请求已达到本秒处理上限，清空请求列表

    def random_sort(self):  # 随机算法
        print('Acting requset in random...')
        for i in random.sample(self.requestList, self.n):
            self.responseList.append(i)
        self.response_request(self.responseList)
        # print(self.responseList)
        # 将请求列表存储到数组中，每一项格式为(113, 2, 4, 25, datetime.datetime(2018, 6, 10, 17, 42, 16))

    def first_sort(self):  # 先来先服务算法
        # 因为往请求表中添加数据时，是按照时间顺序添加的，所以无需对时间进行排序,直接取前n条即可
        print('Acting requset in first_in...')
        for i in range(self.n):
            self.responseList.append(self.requestList[i])
        self.response_request(self.responseList)
        # print(self.responseList)

    def speed_sort(self):  # 风速优先算法
        print('Acting requset in speed_first...')
        cursor = self.db.cursor()
        query = ('select id,speed from status order by -speed')
        cursor.execute(query)
        statusList = cursor.fetchall()
        i = 0
        # print(statusList)
        for status in statusList:  # 找出风速最大的请求
            if i >= self.n:
                break
            for req in self.requestList:
                if req[1] == status[0]:
                    self.responseList.append(req)
                    i = i + 1
        self.response_request(self.responseList)
        # print(self.responseList)

    def response_request(self, requestList):  # 相应请求
        print('response request!\n')
        cursor = self.db.cursor()
        print('response list is', requestList)
        for req in requestList:  # 遍历每个请求
            slave_id = req[1]
            tag_speed = req[2]
            tag_temp = req[3]
            req_time = req[4]
            if tag_speed <= 3 and tag_speed >= 0 and tag_temp <= 30 and tag_temp >= 18 and req_time:  # 合法性判断
                query = ('select id,card_id,cur_temp from status where id=%s' %
                         slave_id)  # 在状态表里读取响应从机信息
                cursor.execute(query)
                the_status = cursor.fetchall()
                status = the_status[0]
                # print('status list: \n')
                # print(req[4].strftime("%Y-%m-%d %H:%M:%S"))
                # print(status)

                if status:  # 从机号合法
                    update_query = (
                        'update status set target_temp=%s, speed=%s where id=%s '
                        % (tag_temp, tag_speed, slave_id))  # 更新相应的从机状态
                    cursor.execute(update_query)
                    self.db.commit()  # 更新status表

                    insert_query = (
                        "insert into log (card_id,slave_id,speed,target_temp,cur_temp,req_time) "
                        "values (%s,%s,%s,%s,%s,'%s')" %
                        (status[1], status[0], req[2], req[3], status[2],
                         req[4].strftime("%Y-%m-%d %H:%M:%S")))
                    #   ,%s,%s,%s,%s,%s
                    cursor.execute(insert_query)
                    self.db.commit()  # 添加日志信息
                else:
                    print('request log is not legal!\n')

                delete_query = ('delete from request where slave_id=%s' % req[1]
                                )  # 无论该从控机id是否合法，均删除相应的请求信息
                cursor.execute(delete_query)
                self.db.commit()
                print('delete request id is: %s from database' % req[0])



#
# machine = mainMachine()
# machine.run()
machine = Blueprint('machine', __name__)
executor = ThreadPoolExecutor(1)
m = mainMachine()


@machine.route("/open")
def open():
    m.flag = True
    executor.submit(m.run)
    return Response('ok', 200)


@machine.route("/close")
def close():
    m.exit()
    return Response('ok', 200)


@machine.route('/info')
def status():
    return jsonify({
        'status': m.main_status,
        'power': m.num,
        'scheduling': m.choice
    })


@machine.route('/set', methods=['GET', 'POST'])
def setting():
    if request.method == "POST":
        m.set_number_request(int(request.json['power']))
        m.set_schedule(int(request.json['scheduling']))
        m.set_status(int(request.json['status']))
    return 'ok'