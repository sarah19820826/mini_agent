# Common Error Patterns

## NullPointerException
- **Symptoms**: "java.lang.NullPointerException" in logs
- **Common causes**: Uninitialized dependency, missing config, empty API response
- **Fix**: Check the null field, add null guard or fix upstream

## ConnectionTimeout
- **Symptoms**: "Connection timed out" or "Read timed out"
- **Common causes**: Network partition, overloaded downstream service, firewall rules
- **Fix**: Check network connectivity, increase timeout, check downstream health

## OutOfMemoryError
- **Symptoms**: "java.lang.OutOfMemoryError: Java heap space"
- **Common causes**: Memory leak, large batch processing, insufficient heap
- **Fix**: Profile memory usage, increase -Xmx, optimize data loading
