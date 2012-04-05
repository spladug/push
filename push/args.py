import argparse
import collections


__all__ = ["parse_args", "ArgumentError"]


class MutatingAction(argparse.Action):
    def __init__(self, *args, **kwargs):
        self.type_to_mutate = kwargs.pop("type_to_mutate")
        argparse.Action.__init__(self, *args, **kwargs)

    def get_attr_to_mutate(self, namespace):
        o = getattr(namespace, self.dest, None)
        if not o:
            o = self.type_to_mutate()
            setattr(namespace, self.dest, o)
        return o


class SetAddConst(MutatingAction):
    "Action that adds a constant to a set."
    def __init__(self, *args, **kwargs):
        kwargs["nargs"] = 0
        MutatingAction.__init__(self, *args, type_to_mutate=set, **kwargs)

    def __call__(self, parser, namespace, values, option_string=None):
        s = self.get_attr_to_mutate(namespace)

        if hasattr(self.const, "__iter__"):
            for x in self.const:
                s.add(x)
        else:
            s.add(self.const)


class DictAddConstKey(MutatingAction):
    "Action that adds an argument to a dict with a constant key."
    def __init__(self, *args, **kwargs):
        MutatingAction.__init__(self, *args, type_to_mutate=dict, **kwargs)

    def __call__(self, parser, namespace, values, option_string=None):
        d = self.get_attr_to_mutate(namespace)
        value = values[0]
        d[self.const] = value


class AppendHostOrAlias(MutatingAction):
    """Action that appends hosts to a host list, and extends the host list with
    the contents of aliases."""
    def __init__(self, *args, **kwargs):
        self.all_hosts = kwargs.pop("all_hosts")
        self.aliases = kwargs.pop("aliases")
        MutatingAction.__init__(self, *args, type_to_mutate=list, **kwargs)

    def __call__(self, parser, namespace, values, option_string=None):
        host_list = self.get_attr_to_mutate(namespace)
        queue = collections.deque(values)
        while queue:
            host_or_alias = queue.popleft()

            # backwards compatibility with perl version
            if " " in host_or_alias:
                queue.extend(x.strip() for x in host_or_alias.split(" "))
                continue

            if host_or_alias in self.all_hosts:
                host_list.append(host_or_alias)
            elif host_or_alias in self.aliases:
                host_list.extend(self.aliases[host_or_alias])
            else:
                raise argparse.ArgumentError(self,
                                             'unknown host or alias "%s"' %
                                             host_or_alias)


class DeployCommand(MutatingAction):
    """Intercepts -r's arguments and ensures the restart commands are properly
    prefixed."""

    def __init__(self, *args, **kwargs):
        MutatingAction.__init__(self, *args, type_to_mutate=list, **kwargs)

    def __call__(self, parser, namespace, values, option_string=None):
        value = values[0]
        prefix = ""
        if value in ("all", "apps"):
            prefix = "restart-"

        command_list = self.get_attr_to_mutate(namespace)
        command_list.append(prefix + value)


class KillCommand(MutatingAction):
    """Prefixes -k's arguments with "kill-" for the deploy script's sake"""

    def __init__(self, *args, **kwargs):
        MutatingAction.__init__(self, *args, type_to_mutate=list, **kwargs)

    def __call__(self, parser, namespace, values, option_string=None):
        command_list = self.get_attr_to_mutate(namespace)
        command_list.append("kill-" + values[0])


class StoreIfHost(argparse.Action):
    "Stores value if it is a known host."
    def __init__(self, *args, **kwargs):
        self.all_hosts = kwargs.pop("all_hosts")
        argparse.Action.__init__(self, *args, **kwargs)

    def __call__(self, parser, namespace, value, option_string=None):
        if value not in self.all_hosts:
            raise argparse.ArgumentError(self, 'unknown host "%s"' % value)
        setattr(namespace, self.dest, value)


class ArgumentError(Exception):
    "Exception raised when there's something wrong with the arguments."
    def __init__(self, message):
        self.message = message

    def __str__(self):
        return self.message


class ArgumentParser(argparse.ArgumentParser):
    """Custom argument parser that raises an exception rather than exiting
    the program"""

    def error(self, message):
        raise ArgumentError(message)


def parse_args(all_hosts, aliases, namespace=None):
    parser = ArgumentParser(description="Deploy stuff to servers.",
                            epilog="To deploy all code: push -h apps "
                                   "-pc -dc -r all",
                            add_help=False)

    parser.add_argument("-h", dest="hosts", metavar="HOST", required=True,
                        action=AppendHostOrAlias, nargs="+",
                        all_hosts=all_hosts, aliases=aliases,
                        help="hosts or groups to execute commands on")
    parser.add_argument("--sleeptime", dest="sleeptime", nargs="?",
                        type=int, default=5,
                        metavar="SECONDS",
                        help="time in seconds to sleep between hosts")

    flags_group = parser.add_argument_group("flags")
    flags_group.add_argument("-t", dest="testing", action="store_true",
                             help="testing: print but don't execute")
    flags_group.add_argument("-q", dest="quiet", action="store_true",
                             help="quiet: no output except errors. implies "
                                  "--no-input")
    flags_group.add_argument("--no-irc", dest="notify_irc",
                             action="store_false",
                             help="don't announce actions in irc")
    flags_group.add_argument("--no-static", dest="build_static",
                             action="store_false",
                             help="don't build static files")
    flags_group.add_argument("--no-input", dest="auto_continue",
                             action="store_true",
                             help="don't wait for input after deploy")

    startat_shuffle = parser.add_mutually_exclusive_group()
    startat_shuffle.add_argument("--startat", dest="start_at",
                                 action=StoreIfHost, nargs='?',
                                 all_hosts=all_hosts,
                                 help="skip to this position in the host list")
    startat_shuffle.add_argument("--shuffle", dest="shuffle",
                                 action="store_true", help="shuffle host list")

    parser.add_argument("--help", action="help", help="display this help")

    deploy_group = parser.add_argument_group("deploy")
    deploy_group.add_argument("-pc", dest="fetches", default=set(),
                              action=SetAddConst, const=["public", "private"],
                              help="short for -ppu -ppr")
    deploy_group.add_argument("-ppu", dest="fetches",
                              action=SetAddConst, const="public",
                              help="git-fetch the public repo")
    deploy_group.add_argument("-ppr", dest="fetches",
                              action=SetAddConst, const="private",
                              help="git-fetch the private repo")
    deploy_group.add_argument("-pla", dest="fetches",
                              action=SetAddConst, const="i18n",
                              help="git-fetch the i18n repo")
    deploy_group.add_argument("-dc", dest="deploys", default=set(),
                              action=SetAddConst, const=["public", "private"],
                              help="short for -dpu -dpr")
    deploy_group.add_argument("-dpu", dest="deploys",
                              action=SetAddConst, const="public",
                              help="deploy the public repo")
    deploy_group.add_argument("-dpr", dest="deploys",
                              action=SetAddConst, const="private",
                              help="deploy the private repo")
    deploy_group.add_argument("-dla", dest="deploys",
                              action=SetAddConst, const="i18n",
                              help="deploy the i18n repo")
    deploy_group.add_argument("-publicrev", dest="revisions", default={},
                              metavar="REF", action=DictAddConstKey,
                              const="public", nargs=1,
                              help="revision to deploy to public repo")
    deploy_group.add_argument("-privaterev", dest="revisions", default={},
                              metavar="REF", action=DictAddConstKey,
                              const="private", nargs=1,
                              help="revision to deploy to private repo")
    deploy_group.add_argument("-langrev", dest="revisions", default={},
                              metavar="REF", action=DictAddConstKey,
                              const="i18n", nargs=1,
                              help="revision to deploy to i18n repo")

    parser.add_argument("-r", dest="deploy_commands", nargs=1,
                        metavar="COMMAND", action=DeployCommand,
                        help="deploy command to execute")
    parser.add_argument("-k", dest="deploy_commands", nargs=1,
                        action=KillCommand, choices=["all", "apps"],
                        help="whom to kill on the host")

    args = parser.parse_args(namespace=namespace)

    if args.quiet:
        args.auto_continue = True

    return args