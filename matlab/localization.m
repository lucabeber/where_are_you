% localization.m
% 2D Localization with 3 anchors and multiple anchors

% Clear workspace and command window
clear;
clc;

% Define the positions of the anchors (x, y)
anchors = [0, 0; 10, 0; 5, 8.66]; % Example positions for 3 anchors

% Define the true position of the target (not know, the position that 
% we want to estimate) 
master_true_position = [4, 2];




% Calculate distances from the target to each anchor
distances = sqrt(sum((anchors - master_true_position).^2, 2));

% Display the distances
disp('Distances to each anchor:');
disp(distances);



% Estimate position using 3 anchors
[S,p] = trilateration(anchors, distances);

% Check if the matrix S is invertible
if det(S) < length(S)
    error('Matrix S is not full rank and cannot be inverted');
end

estimated_position_3 = S^-1 * p;
disp('Estimated position with 3 anchors:');
disp(estimated_position_3);

% Add more anchors for multiple anchor localization
anchors = [anchors; 2, 7; 8, 3]; % Adding more anchors
distances = sqrt(sum((anchors - master_true_position).^2, 2));

% Estimate position using multiple anchors
[S2, p2] = trilateration(anchors, distances);
disp('Display S:');
disp(S2);

% Moore-Penrose pseudoinverse
pinv_S2 = (S2' * S2)^-1 * S2';
estimated_position_multi = pinv_S2 * p2;
disp('Estimated position with multiple anchors:');
disp(estimated_position_multi);

% Plotting the results
figure;
hold on;
plot(anchors(:,1), anchors(:,2), 'ro', 'MarkerSize', 10, 'DisplayName', 'Anchors');
plot(master_true_position(1), master_true_position(2), 'bx', 'MarkerSize', 10, 'DisplayName', 'True Position');
plot(estimated_position_3(1), estimated_position_3(2), 'g+', 'MarkerSize', 10, 'DisplayName', 'Estimated Position (3 Anchors)');
plot(estimated_position_multi(1), estimated_position_multi(2), 'ms', 'MarkerSize', 10, 'DisplayName', 'Estimated Position (Multiple Anchors)');
legend;
xlabel('X Position');
ylabel('Y Position');
title('2D Localization with Anchors');
grid on;
hold off;

% What happens if the anchors are on the same line?
anchors = [0, 0; 10, 0; 20, 0]; % Anchors on the same line
distances = sqrt(sum((anchors - master_true_position).^2, 2));

% Estimate position using 3 anchors
[S3,p3] = trilateration(anchors, distances);

% Check if the matrix S is invertible
if det(S3) == 0
    % Display the rank of the matrix
    disp('Rank of S:');
    disp(rank(S3));
end


% trilateration function 
function [S, p] = trilateration(anchors, distances)
    % Number of anchors
    n = size(anchors, 1);
    
    % Initialize matrices
    S = zeros(n-1, 2);
    p = zeros(n-1, 1);
    
    % Iterate over all anchors
    for i = 1:n-1
        % Fill the matrices
        S(i, :) = 2*[anchors(i+1, 1) - anchors(i, 1), anchors(i+1, 2) - anchors(i, 2)];
        p(i) = - distances(i+1)^2  + distances(i)^2 + anchors(i+1, 1)^2 - anchors(i, 1)^2 + anchors(i+1, 2)^2 - anchors(i, 2)^2;
    end
end