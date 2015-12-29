import collections
import yaml

tree = lambda: collections.defaultdict(tree)

# register a recursive defaultdict with pyyaml
yaml.add_representer(collections.defaultdict,
                     yaml.representer.Representer.represent_dict)

def tree_load(stream, Loader=yaml.Loader):
    class TreeLoader(Loader):
        pass
    def construct_mapping(loader, node):
        data = tree()
        data.update(loader.construct_pairs(node))
        return data

    TreeLoader.add_constructor(
        yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
        construct_mapping)
    return yaml.load(stream, TreeLoader)


class FormatError(Exception):
    """An exception thrown when the YAML document isn't formatted correctly"""
    pass


class Checklist:
    """Manipulates a checklist of items backed by a yaml document. 

    Currently the checklist is aimed at recording when specific MR series are
    to be blacklisted (i.e. deemed to be problematic in someway and so ought to
    be ignored) for specific datman processing stages. 

    See tests/test_checklist.py for examples of use, but in short: 

        import datman
        c = datman.checklist.load(yamlfile)

        c.blacklist("dm-proc-rest", "DTI_CMH_H001_01_01_T1_MPRAGE", 
            "Truncated scan")

        assert c.is_blacklisted("dm-proc-rest", "DTI_CMH_H001_01_01_T1_MPRAGE")

        datman.checklist.save(c, yamlfile)

    The underlying YAMl document is expected to have the following format (but 
    may also have other sections): 

        blacklist: 
            stage: 
                series:
                ...
            ... 

    That is, the top-level must be a dictionary, and entries below it must also 
    be dictionaries. 
    """

    def __init__(self, stream=None):
        if not stream:
            self.data = tree()
        else:
            self.data = tree_load(stream, yaml.SafeLoader) or tree()
        
        if not isinstance(self.data, dict):
            raise FormatError("root node is not a dict")

        self._blacklist = self.data['blacklist']
        
        if not isinstance(self._blacklist, dict):
            raise FormatError("node /blacklist does not contain a dict")
    
    def blacklist(self, section, key, value=None):
        if not self.is_blacklisted(section, key): 
            self._blacklist[section][key] = value

    def is_blacklisted(self, section, key):
        _section = self._blacklist[section]

        if not isinstance(_section, dict):
            raise FormatError("/blacklist/{} does not contain dicts".format(section))

        return key in self._blacklist[section]

    def unblacklist(self, section, key):
        try:
            del self._blacklist[section][key]
        except KeyError:
            pass

    def save(self, stream):
        yaml.dump(self.data, stream, default_flow_style=False)

    def __str__(self):
        return yaml.dump(self.data, default_flow_style=False)

    def __repr__(self):
        return str(self)


def load(stream_or_file=None):
    """Convenience method for loading a checklist from a file or stream"""
    stream = stream_or_file
    if isinstance(stream_or_file, basestring):
        stream = open(stream_or_file, 'r')
    return Checklist(stream)

def save(checklist, stream_or_file):
    """Convenience method for saving a checklist from a file or stream"""
    stream = stream_or_file
    if isinstance(stream_or_file, basestring):
        stream = open(stream_or_file, 'w')

    checklist.save(stream)
