package com.mattvena.powerlifting.model;

public class OneRmSetting {
    private double squat = 150.0;
    private double bench = 100.0;
    private double deadlift = 160.0;
    private double ohp = 60.0;
    private int activeSplit = 5; // Default is 5-split
    
    private boolean fatigueDay1 = false;
    private boolean fatigueDay2 = false;
    private boolean fatigueDay3 = false;
    private boolean fatigueDay4 = false;
    private boolean fatigueDay5 = false;

    public OneRmSetting() {}

    public OneRmSetting(double squat, double bench, double deadlift, double ohp) {
        this.squat = squat;
        this.bench = bench;
        this.deadlift = deadlift;
        this.ohp = ohp;
    }

    public OneRmSetting(double squat, double bench, double deadlift, double ohp, int activeSplit,
                        boolean fatigueDay1, boolean fatigueDay2, boolean fatigueDay3, 
                        boolean fatigueDay4, boolean fatigueDay5) {
        this.squat = squat;
        this.bench = bench;
        this.deadlift = deadlift;
        this.ohp = ohp;
        this.activeSplit = activeSplit;
        this.fatigueDay1 = fatigueDay1;
        this.fatigueDay2 = fatigueDay2;
        this.fatigueDay3 = fatigueDay3;
        this.fatigueDay4 = fatigueDay4;
        this.fatigueDay5 = fatigueDay5;
    }

    public double getSquat() {
        return squat;
    }

    public void setSquat(double squat) {
        this.squat = squat;
    }

    public double getBench() {
        return bench;
    }

    public void setBench(double bench) {
        this.bench = bench;
    }

    public double getDeadlift() {
        return deadlift;
    }

    public void setDeadlift(double deadlift) {
        this.deadlift = deadlift;
    }

    public double getOhp() {
        return ohp;
    }

    public void setOhp(double ohp) {
        this.ohp = ohp;
    }

    public int getActiveSplit() {
        return activeSplit;
    }

    public void setActiveSplit(int activeSplit) {
        this.activeSplit = activeSplit;
    }

    public boolean isFatigueDay1() {
        return fatigueDay1;
    }

    public void setFatigueDay1(boolean fatigueDay1) {
        this.fatigueDay1 = fatigueDay1;
    }

    public boolean isFatigueDay2() {
        return fatigueDay2;
    }

    public void setFatigueDay2(boolean fatigueDay2) {
        this.fatigueDay2 = fatigueDay2;
    }

    public boolean isFatigueDay3() {
        return fatigueDay3;
    }

    public void setFatigueDay3(boolean fatigueDay3) {
        this.fatigueDay3 = fatigueDay3;
    }

    public boolean isFatigueDay4() {
        return fatigueDay4;
    }

    public void setFatigueDay4(boolean fatigueDay4) {
        this.fatigueDay4 = fatigueDay4;
    }

    public boolean isFatigueDay5() {
        return fatigueDay5;
    }

    public void setFatigueDay5(boolean fatigueDay5) {
        this.fatigueDay5 = fatigueDay5;
    }
}
