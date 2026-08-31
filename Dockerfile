FROM freqtradeorg/freqtrade:stable
CMD ["freqtrade", "trade", "--config", "config.json", "--strategy", "SampleStrategy"]

