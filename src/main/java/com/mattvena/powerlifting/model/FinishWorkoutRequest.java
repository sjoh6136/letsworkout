package com.mattvena.powerlifting.model;

import java.util.List;

public class FinishWorkoutRequest {
    private int split;
    private int week;
    private String day;
    private List<WorkoutLog> logs;

    public FinishWorkoutRequest() {}

    public FinishWorkoutRequest(int split, int week, String day, List<WorkoutLog> logs) {
        this.split = split;
        this.week = week;
        this.day = day;
        this.logs = logs;
    }

    public int getSplit() {
        return split;
    }

    public void setSplit(int split) {
        this.split = split;
    }

    public int getWeek() {
        return week;
    }

    public void setWeek(int week) {
        this.week = week;
    }

    public String getDay() {
        return day;
    }

    public void setDay(String day) {
        this.day = day;
    }

    public List<WorkoutLog> getLogs() {
        return logs;
    }

    public void setLogs(List<WorkoutLog> logs) {
        this.logs = logs;
    }
}
