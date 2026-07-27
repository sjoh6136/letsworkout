package com.mattvena.powerlifting.model;

public class WorkoutLog {
    private String date;        // yyyy-MM-dd
    private int split;          // 2, 3, 4, 5
    private int week;           // week number (1, 2, 3...)
    private String day;         // Day 1, Day 2...
    private String exercise;    // e.g. Bench Press
    private int setNo;          // set number
    private double targetWeight; // weight target
    private double weight;      // weight lifted
    private int targetReps;     // reps target
    private int reps;           // reps completed
    private double rpe;         // rpe value
    private String status;      // SUCCESS/FAIL

    public WorkoutLog() {}

    public WorkoutLog(String date, int split, int week, String day, String exercise, int setNo, 
                      double targetWeight, double weight, int targetReps, int reps, double rpe, String status) {
        this.date = date;
        this.split = split;
        this.week = week;
        this.day = day;
        this.exercise = exercise;
        this.setNo = setNo;
        this.targetWeight = targetWeight;
        this.weight = weight;
        this.targetReps = targetReps;
        this.reps = reps;
        this.rpe = rpe;
        this.status = status;
    }

    public String getDate() {
        return date;
    }

    public void setDate(String date) {
        this.date = date;
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

    public String getExercise() {
        return exercise;
    }

    public void setExercise(String exercise) {
        this.exercise = exercise;
    }

    public int getSetNo() {
        return setNo;
    }

    public void setSetNo(int setNo) {
        this.setNo = setNo;
    }

    public double getTargetWeight() {
        return targetWeight;
    }

    public void setTargetWeight(double targetWeight) {
        this.targetWeight = targetWeight;
    }

    public double getWeight() {
        return weight;
    }

    public void setWeight(double weight) {
        this.weight = weight;
    }

    public int getTargetReps() {
        return targetReps;
    }

    public void setTargetReps(int targetReps) {
        this.targetReps = targetReps;
    }

    public int getReps() {
        return reps;
    }

    public void setReps(int reps) {
        this.reps = reps;
    }

    public double getRpe() {
        return rpe;
    }

    public void setRpe(double rpe) {
        this.rpe = rpe;
    }

    public String getStatus() {
        return status;
    }

    public void setStatus(String status) {
        this.status = status;
    }
}
