#!/usr/bin/env python3

import rclpy
from rclpy.action import ActionClient
from rclpy.node import Node
from nav_msgs.msg import Odometry  # For reading /odom data
from sensor_msgs.msg import Range
from action_move_interfaces.action import MoveDistance  # Import custom action
from action_move_interfaces.action import Rotate
import numpy as np
from scipy.optimize import minimize
import matplotlib.pyplot as plt
import tf_transformations
import os

class WhereAreYou():
    def __init__(self):
        
        self.anchor_dist = 2
        # Initialize the matrix of distances between the anchors
        self.D_fixed = np.array([[0, 0, 0],
                                [0, 0, self.anchor_dist],
                                [0, self.anchor_dist, 0]])
        

        # Initialize the estimated points P_k, P_k1, and P_k2
        self.P_k = np.zeros((2, 3))
        self.P_k1 = np.zeros((2, 3))
        self.P_k2 = np.zeros((2, 3))

        self.P_relative = np.zeros((2, 3))

    def where_are_you(self, dist_1, dist_2, dist_3):
        # Compute the P matrices for the new matrices
        P_k = self.find_P(dist_1, self.D_fixed)
        P_k1 = self.find_P(dist_2, self.D_fixed)
        P_k2 = self.find_P(dist_3, self.D_fixed)

        print("P_k:\n", P_k)
        print("P_k1:\n", P_k1)
        print("P_k2:\n", P_k2)

        # Compute the relative rotation and translation between the matrices
        R_k, T_k = find_roto_translation(P_k, P_k1, t_k)
        # Find the rotation matrix between vector T and vector t_k
        u = T_k / np.linalg.norm(T_k)
        v = np.array([1, 0])
        theta = np.arctan2(v[1], v[0]) - np.arctan2(u[1], u[0])

        # Construct the rotation matrix
        R_in = np.array([[np.cos(theta[0]), -np.sin(theta[0])],
                        [np.sin(theta[0]),  np.cos(theta[0])]])   
        P_k = R_in @ P_k

        # Rototranslate the P_k1 in the new frame
        P_k1_new = R_in @ (R_k @ P_k1 + T_k)

        # # Compute the relative rotation and translation between the matrices
        R_k1, T_k1 = find_roto_translation(P_k1_new, P_k2, t_k1+t_k)

        # Rototranslate the P_k2 in the new frame
        P_k2_new = R_k1 @ P_k2 + T_k1


    # Find the P matrix that represents the points in the new frame
    def find_P(dist, D_fixed):
        n = len(dist)+1
        D = np.copy(D_fixed)
        # Complete D_fixied with the first row and column
        for i in range(1,n):
            D[0][i] = dist[i-1]**2
            D[i][0] = dist[i-1]**2
        
        # Compute the Gram matrix
        H = np.eye(n) - (1/n) * np.ones((n, n))
        G = -0.5 * H @ D @ H
        
        # Compute the eigenvalues and eigenvectors of the Gram matrix
        V, U = np.linalg.eig(G) 
        
        # Extract the eigenvectors corresponding to the eigenvalues different from 0
        U = U[:, V > 1e-6]
        V = np.diag(V[V > 1e-6])

        # Compute P
        P = (U @ np.sqrt(V)).T

        # Translate the points of P so that the first point is at the origin
        P = P - P[:, 0].reshape(-1, 1)

        return P

    # Find the relative rotation and translation between two matrices
    def find_roto_translation(P_pre, P_cur, t_k):
        theta = 0
        T = np.array([0,0])

        alpha = 1
        
        def fun(x):
            R = np.array([[np.cos(x[0]), -np.sin(x[0])],
                    [np.sin(x[0]),  np.cos(x[0])]])
            return np.linalg.norm(P_pre[:, 1:3] - (R @ (alpha * S @ P_cur[:, 1:3]) + np.array([[x[1]],[x[2]]])), ord='fro')

        x0 = np.array([theta, T[0], T[1]])
        # Decrease minimum step size to increase precision
        options = {'disp': True, 'maxiter': 100}  # Options for the optimizer

        S = np.eye(2)
        # First optimization using 
        result = minimize(fun, x0, method='BFGS', options=options)
        x = result.x
        R = np.array([[np.cos(x[0]), -np.sin(x[0])],
                    [np.sin(x[0]),  np.cos(x[0])]]) @ S
        T = np.array([[x[1]],[x[2]]])
        print("Translation Norm:", np.linalg.norm(T))

        if abs(np.linalg.norm(T-P_pre[:,0]) - np.linalg.norm(t_k)) > np.linalg.norm(t_k)*0.05:
            # Second optimization with reflected S
            S = np.diag([-1, 1])
            result_reflected = minimize(fun, x0, method='BFGS', options=options)
            x = result_reflected.x
            R = np.array([[np.cos(x[0]), -np.sin(x[0])],
                        [np.sin(x[0]),  np.cos(x[0])]]) @ S
            T = np.array([[x[1]],[x[2]]])
            print("Translation Norm:", np.linalg.norm(T))

        
        return R, T

class MoveDistanceClient(Node):

    def __init__(self):
        super().__init__('move_distance_client')

        # Action client for the move_distance action
        self._action_client = ActionClient(self, MoveDistance, 'move_distance')
        self._action_client_rotate = ActionClient(self, Rotate, 'rotate')

        # Subscribe to /odom for tracking movement
        self.subscription = self.create_subscription(
            Odometry,
            '/odom',
            self.odom_callback,
            10
        )

        # Initialize current position and angle
        self.current_x = 0.0
        self.current_y = 0.0
        self.current_angle = 0.0

        # Initialize current distance between the anchors
        self.current_dist_1 = 0.0
        self.current_dist_2 = 0.0

        


        # Subscribe to /uwb for tracking movement
        self.subscription2 = self.create_subscription(
            Range,
            '/uwb',
            self.uwb_callback,
            10
        )
        timer_period = 0.1  # seconds
        self.timer = self.create_timer(timer_period, self.timer_callback)
        self.status = 0
        self.flag = True
        
        # Parameters for the relative localization
        self.ancor_dist = 2

        

    def timer_callback(self):
        
        if self.status == 0:
            if self.flag:
                # self.D_k1 = self.compute_distance_matrix(self.current_dist_1, self.current_dist_2, self.ancor_dist)
                self.send_goal(1.0, 0.0)
                self.flag = False
        if self.status == 1:
            if self.flag:
                self.send_rotation(90.0)
                self.flag = False
        if self.status == 2:
            if self.flag:
                self.send_goal(0.0, 1.0)
                self.flag = False
                # os.system('ros2 run ')
        if self.status == 3:
            self.get_logger().info('Both goals successfully reached! Starting relative localization')
            ## relative localization
            if self.flag:
                self.flag = False

                # Find the relative position between the anchors and the robot using where are you
                
                # Launch node to control the robot with the keyboard
                os.system('ros2 run teleop_twist_keyboard teleop_twist_keyboard')

            
        
    def odom_callback(self, msg):
        """Callback to capture odometry data (current position)."""
        self.current_x = msg.pose.pose.position.x
        self.current_y = msg.pose.pose.position.y
        orientation_q = msg.pose.pose.orientation
        orientation_list = [orientation_q.x, orientation_q.y, orientation_q.z, orientation_q.w]
        (_, _, yaw) = tf_transformations.euler_from_quaternion(orientation_list)
        self.current_angle = yaw

    def uwb_callback(self, msg):
        """Callback to capture uwb data (current distance between the anchors)."""
        if msg.header.frame_id == 'uwb1':
            self.current_dist_1 = msg.range
        elif msg.header.frame_id == 'uwb2':
            self.current_dist_2 = msg.range

    def send_goal(self, x_goal, y_goal):
        """Send a goal to the action server."""
        self.get_logger().info(f'Sending goal to x: {x_goal}, y: {y_goal}')
        
        goal_msg = MoveDistance.Goal()
        goal_msg.x = x_goal
        goal_msg.y = y_goal

        self._action_client.wait_for_server()
        send_goal_future = self._action_client.send_goal_async(goal_msg)
        send_goal_future.add_done_callback(self.goal_response_callback)

    def goal_response_callback(self, future):
        """Handle the response from the action server."""
        goal_handle = future.result()
        
        if not goal_handle.accepted:
            self.get_logger().info('Goal rejected')
            return
        
        self.get_logger().info('Goal accepted')

        # Wait for the result of the goal
        get_result_future = goal_handle.get_result_async()
        get_result_future.add_done_callback(self.get_result_callback)

    def get_result_callback(self, future):
        """Handle the result from the action server."""
        result = future.result().result
        self.get_logger().info(f'Final position: x: {result.actual_x}, y: {result.actual_y}')

        # Save 
        
        
        self.status += 1
        self.flag = True
    
    def send_rotation(self, angle):
        """Send a goal to the action server."""
        self.get_logger().info(f'Sending rotation goal to {angle} degrees')
        
        goal_msg = Rotate.Goal()
        goal_msg.rotation_angle = angle

        self._action_client_rotate.wait_for_server()
        send_goal_future = self._action_client_rotate.send_goal_async(goal_msg)
        send_goal_future.add_done_callback(self.goal_response_callback_rotation)

    def goal_response_callback_rotation(self, future):
        """Handle the response from the action server."""
        goal_handle = future.result()
        
        if not goal_handle.accepted:
            self.get_logger().info('Goal rejected')
            return
        
        self.get_logger().info('Goal accepted')

        # Wait for the result of the goal
        get_result_future = goal_handle.get_result_async()
        get_result_future.add_done_callback(self.get_result_callback_rotation)
    
    def get_result_callback_rotation(self, future):
        """Handle the result from the action server."""
        result = future.result().result
        self.get_logger().info(f'Final angle: {result.actual_rotation_angle}')
        
        self.status += 1
        self.flag = True

    

def main(args=None):
    rclpy.init(args=args)
    client = MoveDistanceClient()

    # Get initial odometry before sending the goal
    client.get_logger().info(f'Initial position: x: {client.current_x}, y: {client.current_y}')

    rclpy.spin(client)

    client.destroy_node()

    # test where are we
    # N_0_k = np.array([0, 0])
    # t_k = np.array([-1, 0])
    # N_0_k1 = N_0_k + t_k
    # t_k1 = np.array([0, -1])
    # N_0_k2 = N_0_k1 + t_k1

    # # Define the new matrices N_k, N_k1, and N_k2
    # N_1 = np.array([6, 4])  # Example vector, replace with actual values
    # N_2 = np.array([1, 2])  # Example vector, replace with actual values

    # N_k = np.column_stack((N_0_k, N_1, N_2))
    # N_k1 = np.column_stack((N_0_k1, N_1, N_2))
    # N_k2 = np.column_stack((N_0_k2, N_1, N_2))

    # # Compute the distance matrices for the new matrices
    # D_k = np.zeros((N_k.shape[1], N_k.shape[1]))
    # D_k1 = np.zeros((N_k1.shape[1], N_k1.shape[1]))
    # D_k2 = np.zeros((N_k2.shape[1], N_k2.shape[1]))

    # for i in range(N_k.shape[1]):
    #     for j in range(N_k.shape[1]):
    #         D_k[i, j] = np.linalg.norm(N_k[:, i] - N_k[:, j])**2
    #         D_k1[i, j] = np.linalg.norm(N_k1[:, i] - N_k1[:, j])**2
    #         D_k2[i, j] = np.linalg.norm(N_k2[:, i] - N_k2[:, j])**2

    # # Compute the P matrices for the new matrices
    # P_k = find_P(np.sqrt(D_k[0, 1:]), D_k)
    # P_k1 = find_P(np.sqrt(D_k1[0, 1:]), D_k1)
    # P_k2 = find_P(np.sqrt(D_k2[0, 1:]), D_k2)

    # print("P_k:\n", P_k)
    # print("P_k1:\n", P_k1)
    # print("P_k2:\n", P_k2)

    # # Compute the relative rotation and translation between the matrices
    # R_k, T_k = find_roto_translation(P_k, P_k1, t_k)
    # # Find the rotation matrix between vector T and vector t_k
    # u = T_k / np.linalg.norm(T_k)
    # v = np.array([1, 0])
    # theta = np.arctan2(v[1], v[0]) - np.arctan2(u[1], u[0])

    # # Construct the rotation matrix
    # R_in = np.array([[np.cos(theta[0]), -np.sin(theta[0])],
    #                 [np.sin(theta[0]),  np.cos(theta[0])]])   
    # P_k = R_in @ P_k

    # # Rototranslate the P_k1 in the new frame
    # P_k1_new = R_in @ (R_k @ P_k1 + T_k)

    # # # Compute the relative rotation and translation between the matrices
    # R_k1, T_k1 = find_roto_translation(P_k1_new, P_k2, t_k1+t_k)

    # # Rototranslate the P_k2 in the new frame
    # P_k2_new = R_k1 @ P_k2 + T_k1

    # # Plot the results
    # plt.figure()
    # plt.plot(P_k[0, :], P_k[1, :], 'bo', markersize=10, label='P_k')
    # plt.plot(P_k1_new[0, :], P_k1_new[1, :], 'k*', markersize=10, label='P_k1_new')
    # plt.plot(P_k2_new[0, :], P_k2_new[1, :], 'rs', markersize=10, label='P_k2_new')
    # plt.axis('equal')
    # plt.legend()
    # plt.grid(True)
    # plt.show()

    

    rclpy.shutdown()


if __name__ == '__main__':
    main()

