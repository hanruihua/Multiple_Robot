#!/usr/bin/env python3
import rospy
import numpy as np
import threading
from gazebo_msgs.msg import WorldState
from gazebo_msgs.msg import ModelStates
from geometry_msgs.msg import Twist
from geometry_msgs.msg import Pose
from std_msgs.msg import String
from rvo_obs import rvo_obs
import torch
import sys
from math import sin, cos, pi, atan2
import time
import re
from utils import start_goal_list, cal_des_omni, cal_yaw
import os

num_robot = 12
mode = 3 # mode: 3 circle, 2 random
v_max = 1.5 # max velocity
robot_name_list = ['agent1', 'agent2','agent3','agent4','agent5', 'agent6', 'agent7','agent8','agent9','agent10', 'agent11', 'agent12']
robot_collision_radius = 0.4
neighbors_region = 4
w_max = 2
episode_num = 20

# filename = '/home/han/catkin_ws/src/master_multirobot/master_planning/rl_rvo/project/drl_rvo_nav/ppo_save/result/move10_1/move10.pt'
filename = os.path.dirname(os.path.realpath(__file__))+'/project/drl_rvo_nav/ppo_save/result/move10_2/move10.pt'

pub=rospy.Publisher('/global/multi_vel', WorldState, queue_size=100)

goal_list = []

if mode==3:
	goal_list1, goal_list2 = start_goal_list(num_robot=num_robot, mode=mode, interval=1.5, upper=8, lower= 0, right=8, circle_point=[5, 5], radius=3)
	goal_list=goal_list1.copy()

elif mode==2:
	random_list=start_goal_list(num_robot=num_robot, mode=mode, interval=1.5, upper=8, lower= 0, right=8, circle_point=[5, 5], radius=3)
	goal_list=random_list

model = torch.load(filename)
model.eval()

moving_state_list = [None] * num_robot
robot_state_list = [None] * num_robot
name_list = [None] * num_robot
obs1_list = [None] * num_robot

pose_list=[None] * num_robot
# yaw_list = [None] * num_robot
arrive_flag_current = False
goal_flag = True

def callback(data):
	start_time = time.time()
	arrive_flag_list = []
	global goal_list, goal_flag

	for index, name in enumerate(data.name):
		
		if name in robot_name_list:

			id_agent = int(re.findall('\d+', name)[0])
			
			p_x = data.pose[index].position.x
			p_y = data.pose[index].position.y

			vel_x = data.twist[index].linear.x
			vel_y = data.twist[index].linear.y

			yaw = cal_yaw(data.pose[index].orientation)

			collision_range = robot_collision_radius

			moving_state = np.array([p_x, p_y, vel_x, vel_y, collision_range])
			moving_state_list[id_agent - 1] = moving_state

			goal_position = goal_list[id_agent-1]
			des_x, des_y = cal_des_omni([p_x, p_y], goal_position, v_max)

			robot_state = np.array([p_x, p_y, vel_x, vel_y, robot_collision_radius, des_x, des_y])
			obs1 = np.array([vel_x, vel_y, des_x, des_y, robot_collision_radius, yaw])

			robot_state_list[id_agent - 1] = robot_state
			obs1_list[id_agent - 1] = obs1
			name_list[id_agent - 1] = name

			# yaw_list[id_agent - 1] = yaw
			pose_list[id_agent - 1] = data.pose[index]

			if des_x == 0 and des_y == 0:
				arrive_flag = 1
			else: 
				arrive_flag = 0
			
			arrive_flag_list.append(arrive_flag)
	
	if min(arrive_flag_list):

		print(1)

		goal_flag = not goal_flag

		if goal_flag:
			goal_list = goal_list1.copy()
		else:
			goal_list = goal_list2.copy()

def rl_rvo():
	rospy.init_node('rl_rvo', anonymous=True)
	
	rate=rospy.Rate(50)
	rospy.Subscriber("/gazebo/model_states", ModelStates, callback)
	
	while not rospy.is_shutdown():
		
		

		ws = WorldState()
		for i in range(num_robot):
			
			if moving_state_list[0] is None:
				continue

			moving_state_list2 = moving_state_list[:]
			robot_state = robot_state_list[i]
			name = name_list[i]
			
			del moving_state_list2[i]
			
			p_x = robot_state[0]
			p_y = robot_state[1]
			vel_x = robot_state[2]
			vel_y = robot_state[3]

			des_x = robot_state[5]
			des_y = robot_state[6]

			def rs_function(moving_state):
				
				dif_x = moving_state[0] - p_x
				dif_y = moving_state[1] - p_y
				dis = np.sqrt( dif_x**2 + dif_y**2)

				return dis

			filter_moving_list = list(filter(lambda m: rs_function(m) <= neighbors_region, moving_state_list2))
			sorted_moving_list = sorted(filter_moving_list, key=lambda m: rs_function(m))

			rvo = rvo_obs(robot_state, sorted_moving_list)
			rvo_list = rvo.config_rvo_obs4()
			
			if len(rvo_list) == 0:
				rvo_array_flat = np.zeros(8,)
			else:
				rvo_array = np.concatenate(rvo_list)
				rvo_array_flat = rvo_array.flatten()

			obs1 = obs1_list[i]
			obs = np.concatenate((obs1, rvo_array_flat)) 

			# with torch.no_grad():
			obs = torch.as_tensor(obs, dtype=torch.float32)
			action = model.act(obs, std_factor=0.0001)
			abs_action = 0.5 * action + np.array([vel_x, vel_y])
			abs_action = np.clip(abs_action, -v_max, v_max)
			robot_name = name_list[i]
		
			tw = Twist()

			# v, w = omni2diff(des_x, des_y, yaw)

			if des_x == 0 and des_y == 0:
				tw.linear.x = 0
				tw.linear.y = 0
				tw.linear.z = 0
			else:
				tw.linear.x = abs_action[0]
				tw.linear.y = abs_action[1]
				tw.linear.z = 0

			# tw.linear.x = des_x
			# tw.linear.y = des_y
			# tw.linear.z = 0

			# tw.linear.x = v
			# tw.angular.z = w
			# tw.linear.z = 1

			robot_pose = pose_list[i]

			ws.name.append(robot_name)
			ws.twist.append(tw)
			ws.pose.append(robot_pose)

		pub.publish(ws)
		print('publish velocity successfully')
		rate.sleep()

def spin():
	rospy.spin()


if __name__=='__main__':
	thread = threading.Thread(target=spin)
	rl_rvo()
	thread.start()
	
	