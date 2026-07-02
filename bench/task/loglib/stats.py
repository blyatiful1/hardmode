def count_by_level(entries, counts={}):
    for e in entries:
        counts[e.level] = counts.get(e.level, 0) + 1
    return counts


def summarize(entries):
    return count_by_level(entries)
